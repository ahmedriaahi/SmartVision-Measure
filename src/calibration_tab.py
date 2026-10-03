"""
Onglet de calibration caméra par mire ChArUco.
Station fixe industrielle - Partie 1 du pipeline AI Post-Prod Calibration Tool.

Ce module expose CalibrationTab, un QWidget autonome destiné à être intégré
dans un QTabWidget (voir main.py). Il émet un signal `status_message` au lieu
d'utiliser une barre de statut propre, pour partager celle de la fenêtre
principale avec les autres onglets.

Fonctionnalités :
    - Aperçu vidéo temps réel de la caméra avec détection live du board
    - Capture d'image par appui sur la touche S (Save Picture)
    - Compteur d'images capturées
    - Bouton de lancement de la calibration sur les images capturées
    - Affichage des paramètres de calibration (matrice caméra, distorsion)
    - Graphique de l'erreur de reprojection par image
"""

import os
import sys
from datetime import datetime

import cv2
import numpy as np

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QFont, QKeyEvent
from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QComboBox,
)

sys.path.insert(0, os.path.dirname(__file__))
from charuco_calibrator import CharucoCalibrator
from reprojection_chart import ReprojectionErrorChart


CAPTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "captures")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "calibration_results")
os.makedirs(CAPTURES_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# Emplacement par défaut où la calibration est auto-exportée à la fin d'une
# calibration réussie, pour que l'onglet Modèle puisse la charger directement
# sans action manuelle de l'utilisateur.
DEFAULT_CALIBRATION_PATH = os.path.join(RESULTS_DIR, "calibration_latest.yaml")


class VideoFeedLabel(QLabel):
    """Zone d'affichage vidéo. Capte les appuis clavier (touche S) pour la capture."""

    save_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background-color: #1a1a1a; color: #888888; border-radius: 8px;"
        )
        self.setText("Caméra non démarrée")
        self.setFocusPolicy(Qt.StrongFocus)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_S:
            self.save_requested.emit()
        else:
            super().keyPressEvent(event)

    def set_frame(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(pix)


class CalibrationTab(QWidget):
    """Onglet de calibration ChArUco, intégrable dans un QTabWidget."""

    status_message = Signal(str)
    # Émis avec le chemin du fichier YAML dès qu'une calibration réussie est
    # auto-exportée, pour que l'onglet Modèle puisse se mettre à jour.
    calibration_exported = Signal(str)
    # Émis à chaque frame avec la distance mesurée automatiquement via ArUco.

    def __init__(self, parent=None):
        super().__init__(parent)

        self.calibrator = CharucoCalibrator()
        self.capture = None
        self.camera_index = 0
        self.last_frame = None
        self.last_n_corners = 0
        self.last_calibration_result = None

        # Mesure automatique de distance via marqueurs ArUco (taille par défaut 15mm)

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_frame)

    # ------------------------------------------------------------------
    # Construction de l'interface
    # ------------------------------------------------------------------
    def _build_ui(self):
        root_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        # ---------------- Colonne gauche : vidéo + contrôles caméra -----
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        cam_select_row = QHBoxLayout()
        cam_select_row.addWidget(QLabel("Caméra :"))
        self.camera_combo = QComboBox()
        self.camera_combo.addItems([f"Caméra {i}" for i in range(4)])
        cam_select_row.addWidget(self.camera_combo)
        self.btn_start_cam = QPushButton("Démarrer la caméra")
        self.btn_start_cam.clicked.connect(self._toggle_camera)
        cam_select_row.addWidget(self.btn_start_cam)
        cam_select_row.addStretch()
        left_layout.addLayout(cam_select_row)

        self.video_label = VideoFeedLabel()
        self.video_label.save_requested.connect(self._capture_image)
        left_layout.addWidget(self.video_label, stretch=1)

        info_row = QHBoxLayout()
        self.corners_label = QLabel("Coins détectés : —")
        self.corners_label.setStyleSheet("font-weight: 500;")
        info_row.addWidget(self.corners_label)
        info_row.addStretch()
        hint = QLabel("Appuyez sur [S] pour capturer une image")
        hint.setStyleSheet("color: palette(mid);")
        info_row.addWidget(hint)
        left_layout.addLayout(info_row)

        capture_btn_row = QHBoxLayout()
        self.btn_save_picture = QPushButton("📷 Capturer (S)")
        self.btn_save_picture.clicked.connect(self._capture_image)
        self.btn_save_picture.setMinimumHeight(40)
        capture_btn_row.addWidget(self.btn_save_picture)

        self.btn_load_images = QPushButton("📂 Charger des images existantes")
        self.btn_load_images.clicked.connect(self._load_images_from_disk)
        self.btn_load_images.setMinimumHeight(40)
        capture_btn_row.addWidget(self.btn_load_images)
        left_layout.addLayout(capture_btn_row)


        splitter.addWidget(left_panel)

        # ---------------- Colonne droite : liste images + calibration --
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        images_group = QGroupBox("Images capturées (0)")
        self.images_group = images_group
        images_layout = QVBoxLayout(images_group)
        self.image_list = QListWidget()
        images_layout.addWidget(self.image_list)

        list_btn_row = QHBoxLayout()
        self.btn_remove_selected = QPushButton("Retirer la sélection")
        self.btn_remove_selected.clicked.connect(self._remove_selected_image)
        list_btn_row.addWidget(self.btn_remove_selected)
        self.btn_clear_all = QPushButton("Tout effacer")
        self.btn_clear_all.clicked.connect(self._clear_all_images)
        list_btn_row.addWidget(self.btn_clear_all)
        images_layout.addLayout(list_btn_row)

        right_layout.addWidget(images_group, stretch=1)

        # Bouton de calibration (le bouton "premier bouton" demandé)
        self.btn_calibrate = QPushButton("⚙ Lancer la calibration de la caméra")
        self.btn_calibrate.setMinimumHeight(44)
        self.btn_calibrate.setStyleSheet(
            "font-weight: 600; background-color: #185FA5; color: white; border-radius: 6px;"
        )
        self.btn_calibrate.clicked.connect(self._run_calibration)
        right_layout.addWidget(self.btn_calibrate)

        # Zone carrée d'interprétation / résultats (paramètres + courbe)
        results_group = QGroupBox("Résultats de calibration")
        results_layout = QVBoxLayout(results_group)

        self.params_text = QTextEdit()
        self.params_text.setReadOnly(True)
        self.params_text.setMaximumHeight(170)
        self.params_text.setFont(QFont("Courier New", 9))
        self.params_text.setPlaceholderText(
            "Les paramètres de calibration (matrice caméra, coefficients "
            "de distorsion, erreur RMS) s'afficheront ici après calibration."
        )
        results_layout.addWidget(self.params_text)

        self.chart = ReprojectionErrorChart()
        results_layout.addWidget(self.chart, stretch=1)

        export_row = QHBoxLayout()
        self.btn_export_json = QPushButton("💾 Exporter (JSON)")
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_export_json.setEnabled(False)
        export_row.addWidget(self.btn_export_json)
        self.btn_export_yaml = QPushButton("💾 Exporter (OpenCV YAML)")
        self.btn_export_yaml.clicked.connect(self._export_yaml)
        self.btn_export_yaml.setEnabled(False)
        export_row.addWidget(self.btn_export_yaml)
        results_layout.addLayout(export_row)

        right_layout.addWidget(results_group, stretch=2)

        splitter.addWidget(right_panel)
        splitter.setSizes([700, 580])

        self.status_message.emit(
            "Prêt. Démarrez la caméra puis capturez au moins "
            f"{self.calibrator.MIN_IMAGES_FOR_CALIBRATION} images du board sous des angles variés."
        )

    # ------------------------------------------------------------------
    # Gestion caméra
    # ------------------------------------------------------------------
    def _toggle_camera(self):
        if self.capture is None:
            index = self.camera_combo.currentIndex()
            cap = cv2.VideoCapture(index)
            if not cap.isOpened():
                QMessageBox.warning(
                    self, "Caméra indisponible",
                    f"Impossible d'ouvrir la caméra {index}. "
                    "Vérifiez le branchement ou choisissez un autre index."
                )
                return
            self.capture = cap
            self.btn_start_cam.setText("Arrêter la caméra")
            self.timer.start(30)  # ~33 FPS
            self.video_label.setFocus()
            self.status_message.emit("Caméra démarrée. Visez le board ChArUco.")
        else:
            self.timer.stop()
            self.capture.release()
            self.capture = None
            self.video_label.setText("Caméra arrêtée")
            self.btn_start_cam.setText("Démarrer la caméra")

    def _update_frame(self):
        if self.capture is None:
            return
        ok, frame = self.capture.read()
        if not ok:
            self.status_message.emit("Erreur de lecture caméra.")
            return

        overlay, n_corners = self.calibrator.detect_and_draw(frame)
        self.last_frame = frame
        self.last_n_corners = n_corners

        self.video_label.set_frame(overlay)
        self.corners_label.setText(f"Coins détectés : {n_corners}")
        self.corners_label.setStyleSheet(
            "font-weight: 500; color: #1D9E75;" if n_corners >= self.calibrator.MIN_CORNERS_PER_IMAGE
            else "font-weight: 500; color: #D85A30;"
        )

    # ------------------------------------------------------------------
    # Capture d'images (touche S ou bouton)
    # ------------------------------------------------------------------
    def _capture_image(self):
        if self.last_frame is None:
            QMessageBox.information(
                self, "Aucune image", "Démarrez la caméra avant de capturer."
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"charuco_{timestamp}.png"
        filepath = os.path.join(CAPTURES_DIR, filename)

        accepted, n_corners, msg = self.calibrator.add_image(
            self.last_frame, name=filename
        )

        if accepted:
            cv2.imwrite(filepath, self.last_frame)
            item = QListWidgetItem(f"✓ {filename}  ({n_corners} coins)")
            self.image_list.addItem(item)
            self.status_message.emit(f"Image capturée : {msg}")
        else:
            self.status_message.emit(f"Image rejetée : {msg}")
            QMessageBox.warning(self, "Capture rejetée", msg)
            return

        self._refresh_image_count()

    def _load_images_from_disk(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Sélectionner des images du board ChArUco",
            CAPTURES_DIR, "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not files:
            return

        n_accepted = 0
        for f in files:
            img = cv2.imread(f)
            if img is None:
                continue
            name = os.path.basename(f)
            accepted, n_corners, msg = self.calibrator.add_image(img, name=name)
            if accepted:
                item = QListWidgetItem(f"✓ {name}  ({n_corners} coins)")
                self.image_list.addItem(item)
                n_accepted += 1

        self._refresh_image_count()
        self.status_message.emit(
            f"{n_accepted}/{len(files)} images chargées et acceptées."
        )

    def _refresh_image_count(self):
        n = self.calibrator.n_images
        self.images_group.setTitle(f"Images capturées ({n})")
        ready = n >= 4
        self.btn_calibrate.setEnabled(ready)
        if n < self.calibrator.MIN_IMAGES_FOR_CALIBRATION:
            self.status_message.emit(
                f"{n} image(s) — minimum recommandé : "
                f"{self.calibrator.MIN_IMAGES_FOR_CALIBRATION} sous des angles variés."
            )

    def _remove_selected_image(self):
        row = self.image_list.currentRow()
        if row < 0:
            return
        # Reconstruction simple : on retire de la liste UI, et on recharge le
        # calibrateur depuis les images restantes pour rester cohérent.
        self.image_list.takeItem(row)
        self._rebuild_calibrator_from_list()

    def _clear_all_images(self):
        reply = QMessageBox.question(
            self, "Confirmer", "Effacer toutes les images capturées de cette session ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.image_list.clear()
            self.calibrator.reset()
            self._refresh_image_count()
            self.chart.clear()
            self.params_text.clear()
            self.btn_export_json.setEnabled(False)
            self.btn_export_yaml.setEnabled(False)

    def _rebuild_calibrator_from_list(self):
        """Recharge le calibrateur depuis les fichiers correspondant aux items restants."""
        remaining_names = []
        for i in range(self.image_list.count()):
            text = self.image_list.item(i).text()
            # format "✓ filename.png  (N coins)"
            name = text.split("  ")[0].replace("✓ ", "").strip()
            remaining_names.append(name)

        self.calibrator.reset()
        for name in remaining_names:
            path = os.path.join(CAPTURES_DIR, name)
            if os.path.exists(path):
                img = cv2.imread(path)
                if img is not None:
                    self.calibrator.add_image(img, name=name)
        self._refresh_image_count()

    # ------------------------------------------------------------------
    # Calibration et affichage des résultats
    # ------------------------------------------------------------------
    def _run_calibration(self):
        try:
            result = self.calibrator.calibrate()
        except ValueError as e:
            QMessageBox.warning(self, "Calibration impossible", str(e))
            return
        except cv2.error as e:
            QMessageBox.critical(
                self, "Erreur OpenCV",
                f"La calibration a échoué :\n{e}\n\n"
                "Vérifiez que les images couvrent des angles et distances variés."
            )
            return

        self.last_calibration_result = result
        self._display_results(result)
        self.btn_export_json.setEnabled(True)
        self.btn_export_yaml.setEnabled(True)


        # Auto-export vers un emplacement fixe pour que l'onglet Modèle
        # puisse récupérer la calibration sans action manuelle.
        try:
            result.save_opencv_yaml(DEFAULT_CALIBRATION_PATH)
            self.calibration_exported.emit(DEFAULT_CALIBRATION_PATH)
        except Exception:
            pass  # l'export manuel via le bouton reste disponible

        self.status_message.emit(
            f"Calibration réussie — RMS = {result.overall_rms_error:.4f} px "
            f"sur {len(result.used_image_names)} images."
        )

    def _display_results(self, result):
        cm = result.camera_matrix
        dc = result.dist_coeffs.flatten()

        quality = (
            "Excellente" if result.overall_rms_error < 0.5 else
            "Bonne" if result.overall_rms_error < 1.0 else
            "Acceptable" if result.overall_rms_error < 2.0 else
            "Insuffisante — recapturer des images"
        )

        text = (
            f"=== PARAMÈTRES DE CALIBRATION ===\n"
            f"Résolution image : {result.image_size[0]} x {result.image_size[1]} px\n"
            f"Images utilisées : {len(result.used_image_names)}\n"
            f"Erreur RMS globale : {result.overall_rms_error:.4f} px  [{quality}]\n\n"
            f"Matrice caméra (intrinsèques) :\n"
            f"  fx = {cm[0,0]:.2f}   fy = {cm[1,1]:.2f}\n"
            f"  cx = {cm[0,2]:.2f}   cy = {cm[1,2]:.2f}\n\n"
            f"Coefficients de distorsion (k1,k2,p1,p2,k3) :\n"
            f"  {', '.join(f'{v:.5f}' for v in dc)}\n"
        )
        self.params_text.setPlainText(text)

        self.chart.update_chart(
            result.used_image_names,
            result.per_image_errors,
            result.overall_rms_error,
        )

    def _export_json(self):
        if self.last_calibration_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la calibration (JSON)",
            os.path.join(RESULTS_DIR, "calibration.json"),
            "JSON (*.json)"
        )
        if path:
            self.last_calibration_result.save_json(path)
            self.status_message.emit(f"Calibration exportée : {path}")

    def _export_yaml(self):
        if self.last_calibration_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter la calibration (OpenCV YAML)",
            os.path.join(RESULTS_DIR, "calibration.yaml"),
            "YAML (*.yaml)"
        )
        if path:
            self.last_calibration_result.save_opencv_yaml(path)
            self.status_message.emit(f"Calibration exportée : {path}")

    def release_camera(self):
        """À appeler depuis la fenêtre principale lors de la fermeture de
        l'application, pour libérer proprement la caméra si elle est active."""
        if self.capture is not None:
            self.timer.stop()
            self.capture.release()
            self.capture = None
