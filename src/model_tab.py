"""
Onglet Modèle : segmentation YOLOv8-seg, mesure dimensionnelle, et
comparaison STL. Partie 2 du pipeline AI Post-Prod Calibration Tool.

Boutons (cahier des charges interface_modele_pfa.doc) :
    1. Démarrer la caméra      6. Capturer le résultat
    2. Arrêter la caméra       7. Exporter les résultats (CSV/JSON)
    3. Activer la segmentation 8. Comparer avec le fichier STL
    4. Afficher les dimensions 9. Réinitialiser
    5. Geler les mesures
    + Panneau d'informations (nom pièce, confiance, L, l, aire, RMS, date/heure)
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
    QGridLayout,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QComboBox,
    QListWidget,
    QListWidgetItem,
)

sys.path.insert(0, os.path.dirname(__file__))
from segmentation_engine import (
    SegmentationEngine,
    DimensionAnalyzer,
    MeasurementExporter,
)
from stl_compare import STLComparator, STL_AVAILABLE
from report_generator import ReportGenerator
from aruco_distance import ArucoScaleEstimator


CAPTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "captures")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "calibration_results")
MEASUREMENTS_DIR = os.path.join(os.path.dirname(__file__), "..", "measurements")
os.makedirs(MEASUREMENTS_DIR, exist_ok=True)



class ModelVideoFeedLabel(QLabel):
    """Zone d'affichage vidéo de l'onglet Modèle (même comportement que
    celle de l'onglet Calibration, dupliquée car les deux onglets doivent
    pouvoir fonctionner indépendamment)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background-color: #1a1a1a; color: #888888; border-radius: 8px;"
        )
        self.setText("Caméra non démarrée")

    def set_frame(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg).scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(pix)


class ModelTab(QWidget):
    """Onglet de segmentation et mesure dimensionnelle, intégrable dans un
    QTabWidget aux côtés de CalibrationTab."""

    status_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.engine = SegmentationEngine()
        self.analyzer = DimensionAnalyzer()
        self.stl_comparator = STLComparator() if STL_AVAILABLE else None

        # Estimation d'échelle mm/pixel via ratio direct marqueurs ArUco
        self.scale_estimator = ArucoScaleEstimator()

        # Distance de travail caméra–pièce en mm.
        # Mise à jour automatiquement via le signal distance_measured
        # émis depuis l'onglet Calibration (mesure ArUco temps réel).
        # Matrice caméra stockée pour recalculer l'échelle à chaque
        # nouvelle mesure de distance sans relire le fichier YAML.
        self._camera_matrix = None

        self.capture = None
        self.camera_index = 0
        self.last_frame = None              # dernier frame brut (live)
        self.frozen_frame = None            # frame gelé (bouton "Geler")
        self.is_frozen = False
        self.segmentation_active = False
        self.last_segmentation = None       # dernier SegmentationResult
        self.last_measurement = None        # dernier DimensionMeasurement
        self.last_stl_comparison = None
        self.measurement_history = []       # liste de DimensionMeasurement, pour export

        self._build_ui()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_frame)

        self._try_autoload_calibration()

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

        cam_row = QHBoxLayout()
        cam_row.addWidget(QLabel("Caméra :"))
        self.camera_combo = QComboBox()
        self.camera_combo.addItems([f"Caméra {i}" for i in range(4)])
        cam_row.addWidget(self.camera_combo)
        cam_row.addStretch()
        left_layout.addLayout(cam_row)

        self.video_label = ModelVideoFeedLabel()
        left_layout.addWidget(self.video_label, stretch=1)

        # --- Ligne de statut segmentation / modèle ---
        seg_status_row = QHBoxLayout()
        self.model_status_label = QLabel("Modèle : aucun chargé")
        self.model_status_label.setStyleSheet("color: #D85A30; font-weight: 500;")
        seg_status_row.addWidget(self.model_status_label)
        seg_status_row.addStretch()
        self.calib_status_label = QLabel("Calibration : non chargée")
        self.calib_status_label.setStyleSheet("color: #D85A30; font-weight: 500;")
        seg_status_row.addWidget(self.calib_status_label)
        left_layout.addLayout(seg_status_row)

        # --- Boutons 1-2 : Démarrer / Arrêter la caméra ---
        cam_btn_row = QHBoxLayout()
        self.btn_start_cam = QPushButton("▶ Démarrer la caméra")
        self.btn_start_cam.clicked.connect(self._start_camera)
        self.btn_start_cam.setMinimumHeight(38)
        cam_btn_row.addWidget(self.btn_start_cam)

        self.btn_stop_cam = QPushButton("■ Arrêter la caméra")
        self.btn_stop_cam.clicked.connect(self._stop_camera)
        self.btn_stop_cam.setMinimumHeight(38)
        self.btn_stop_cam.setEnabled(False)
        cam_btn_row.addWidget(self.btn_stop_cam)
        left_layout.addLayout(cam_btn_row)

        # --- Bouton : Charger une image depuis le disque ---
        # Alternative à la caméra temps réel : permet de charger une image
        # capturée par téléphone ou tout autre appareil, l'affiche dans la
        # zone vidéo, et active exactement le même pipeline de traitement
        # (segmentation, mesures, comparaison STL, rapport).
        self.btn_load_image = QPushButton("🖼 Charger une image (téléphone / fichier)")
        self.btn_load_image.clicked.connect(self._load_image_from_file)
        self.btn_load_image.setMinimumHeight(38)
        self.btn_load_image.setToolTip(
            "Charger une image depuis le disque pour l'analyser sans caméra.\n"
            "Formats supportés : JPG, PNG, BMP, TIFF.\n"
            "Une fois chargée, utilisez les boutons segmentation et dimensions."
        )
        left_layout.addWidget(self.btn_load_image)

        # --- Bouton 3 : Activer la segmentation ---
        self.btn_segment = QPushButton("🧩 Activer la segmentation")
        self.btn_segment.setCheckable(True)
        self.btn_segment.clicked.connect(self._toggle_segmentation)
        self.btn_segment.setMinimumHeight(38)
        left_layout.addWidget(self.btn_segment)

        # --- Bouton charger modèle .pt ---
        self.btn_load_model = QPushButton("📁 Charger un modèle YOLOv8-seg (.pt)")
        self.btn_load_model.clicked.connect(self._load_model)
        left_layout.addWidget(self.btn_load_model)

        # --- Boutons 4-5 : Afficher les dimensions / Geler les mesures ---
        dim_btn_row = QHBoxLayout()
        self.btn_show_dims = QPushButton("📐 Afficher les dimensions")
        self.btn_show_dims.clicked.connect(self._compute_dimensions)
        self.btn_show_dims.setMinimumHeight(38)
        dim_btn_row.addWidget(self.btn_show_dims)

        self.btn_freeze = QPushButton("❄ Geler les mesures")
        self.btn_freeze.setCheckable(True)
        self.btn_freeze.clicked.connect(self._toggle_freeze)
        self.btn_freeze.setMinimumHeight(38)
        dim_btn_row.addWidget(self.btn_freeze)
        left_layout.addLayout(dim_btn_row)

        # --- Boutons 6-7 : Capturer le résultat / Exporter ---
        export_btn_row = QHBoxLayout()
        self.btn_capture_result = QPushButton("📷 Capturer le résultat")
        self.btn_capture_result.clicked.connect(self._capture_result)
        export_btn_row.addWidget(self.btn_capture_result)

        self.btn_export_csv = QPushButton("💾 Exporter CSV")
        self.btn_export_csv.clicked.connect(self._export_csv)
        export_btn_row.addWidget(self.btn_export_csv)

        self.btn_export_json = QPushButton("💾 Exporter JSON")
        self.btn_export_json.clicked.connect(self._export_json)
        export_btn_row.addWidget(self.btn_export_json)
        left_layout.addLayout(export_btn_row)

        splitter.addWidget(left_panel)

        # ---------------- Colonne droite : infos + STL + historique -----
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # --- Panneau d'informations ---
        info_group = QGroupBox("Panneau d'informations")
        info_layout = QGridLayout(info_group)
        self.info_labels = {}
        info_fields = [
            ("piece_name", "Nom de la pièce"),
            ("confidence", "Confiance du modèle"),
            ("length", "Longueur"),
            ("width", "Largeur"),
            ("area", "Aire"),
            ("rms", "RMS de calibration"),
            ("timestamp", "Date et heure de mesure"),
        ]
        for row, (key, label) in enumerate(info_fields):
            lbl = QLabel(f"{label} :")
            lbl.setStyleSheet("color: palette(mid);")
            val = QLabel("—")
            val.setStyleSheet("font-weight: 600;")
            info_layout.addWidget(lbl, row, 0)
            info_layout.addWidget(val, row, 1)
            self.info_labels[key] = val
        right_layout.addWidget(info_group)

        # --- Bouton 8 : Comparer avec le fichier STL ---
        stl_group = QGroupBox("Comparaison avec fichier STL")
        stl_layout = QVBoxLayout(stl_group)

        self.btn_load_stl = QPushButton("📐 Comparer avec le fichier STL")
        self.btn_load_stl.clicked.connect(self._compare_with_stl)
        self.btn_load_stl.setMinimumHeight(38)
        if not STL_AVAILABLE:
            self.btn_load_stl.setEnabled(False)
            self.btn_load_stl.setToolTip("Paquet numpy-stl non installé")
        stl_layout.addWidget(self.btn_load_stl)

        self.stl_result_label = QLabel(
            "Chargez un fichier STL pour comparer les dimensions "
            "théoriques aux dimensions mesurées."
        )
        self.stl_result_label.setWordWrap(True)
        self.stl_result_label.setStyleSheet("font-size: 11px;")
        stl_layout.addWidget(self.stl_result_label)

        # --- Bouton Générer le rapport PDF ---
        self.btn_generate_report = QPushButton("📄 Générer le rapport PDF")
        self.btn_generate_report.clicked.connect(self._generate_report)
        self.btn_generate_report.setMinimumHeight(42)
        self.btn_generate_report.setStyleSheet(
            "font-weight: 600; background-color: #185FA5; "
            "color: white; border-radius: 6px;"
        )
        self.btn_generate_report.setToolTip(
            "Génère un rapport PDF professionnel contenant :\n"
            "• Paramètres de calibration caméra\n"
            "• Mesures dimensionnelles vs STL\n"
            "• Analyse des écarts\n"
            "• Recommandations techniques (calibration, température, "
            "paramètres d'impression 3D)"
        )
        stl_layout.addWidget(self.btn_generate_report)

        right_layout.addWidget(stl_group)

        # --- Historique des mesures ---
        history_group = QGroupBox("Historique des mesures (0)")
        self.history_group = history_group
        history_layout = QVBoxLayout(history_group)
        self.history_list = QListWidget()
        history_layout.addWidget(self.history_list)
        right_layout.addWidget(history_group, stretch=1)

        # --- Bouton 9 : Réinitialiser ---
        self.btn_reset = QPushButton("🔄 Réinitialiser")
        self.btn_reset.clicked.connect(self._reset_all)
        self.btn_reset.setMinimumHeight(38)
        self.btn_reset.setStyleSheet(
            "font-weight: 600; background-color: #993C1D; color: white; border-radius: 6px;"
        )
        right_layout.addWidget(self.btn_reset)

        splitter.addWidget(right_panel)
        splitter.setSizes([700, 580])

        self.status_message.emit(
            "Onglet Modèle prêt. Chargez un modèle YOLOv8-seg (.pt) et "
            "démarrez la caméra pour commencer l'inspection."
        )

    # ------------------------------------------------------------------
    # Chargement automatique de la calibration (Partie 1 -> Partie 2)
    # ------------------------------------------------------------------
    def _try_autoload_calibration(self):
        from calibration_tab import DEFAULT_CALIBRATION_PATH
        if os.path.exists(DEFAULT_CALIBRATION_PATH):
            self.load_calibration(DEFAULT_CALIBRATION_PATH)

    def load_calibration(self, yaml_path):
        """Charge la calibration pour le rapport PDF (RMS).
        L'échelle mm/pixel est calculée via ratio ArUco, pas via la calibration."""
        try:
            fs = cv2.FileStorage(yaml_path, cv2.FILE_STORAGE_READ)
            camera_matrix = fs.getNode("camera_matrix").mat()
            rms = fs.getNode("rms_error").real()
            fs.release()
            if camera_matrix is None:
                raise ValueError("camera_matrix introuvable")
            self._camera_matrix = camera_matrix
            self.info_labels["rms"].setText(f"{rms:.4f} px")
            self.calib_status_label.setText(
                f"Calibration chargée (RMS={rms:.3f}px) — échelle via marqueurs ArUco"
            )
            self.calib_status_label.setStyleSheet("color: #1D9E75; font-weight: 500;")
            self.status_message.emit(f"Calibration chargée depuis {yaml_path}")
        except Exception as e:
            self.calib_status_label.setText("Calibration : erreur de chargement")
            self.calib_status_label.setStyleSheet("color: #D85A30; font-weight: 500;")
            self.status_message.emit(f"Erreur chargement calibration : {e}")

    def on_calibration_exported(self, yaml_path):
        """Slot connecté au signal calibration_exported de CalibrationTab."""
        self.load_calibration(yaml_path)


    def _start_camera(self):
        if self.capture is not None:
            return
        index = self.camera_combo.currentIndex()
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            QMessageBox.warning(
                self, "Caméra indisponible",
                f"Impossible d'ouvrir la caméra {index}."
            )
            return
        self.capture = cap
        self.is_frozen = False
        self.btn_start_cam.setEnabled(False)
        self.btn_stop_cam.setEnabled(True)
        self.timer.start(30)
        self.status_message.emit("Caméra démarrée (onglet Modèle).")

    def _stop_camera(self):
        if self.capture is None:
            return
        self.timer.stop()
        self.capture.release()
        self.capture = None
        self.btn_start_cam.setEnabled(True)
        self.btn_stop_cam.setEnabled(False)
        self.video_label.setText("Caméra arrêtée")
        self.status_message.emit("Caméra arrêtée (onglet Modèle).")

    def _run_segmentation_on_frame(self, frame):
        """
        Exécute la segmentation sur un frame donné (caméra live ou image
        chargée depuis le disque) et met à jour l'affichage + l'état interne.

        Centralise la logique partagée entre _update_frame (caméra live)
        et _toggle_segmentation / _load_image_from_file (mode image statique),
        pour éviter toute divergence de comportement entre les deux modes.
        """
        if not (self.segmentation_active and self.engine.is_loaded):
            return

        seg_result = self.engine.segment(frame)
        self.last_segmentation = seg_result

        if seg_result is not None:
            display_frame = DimensionAnalyzer.draw_annotations(
                frame, None, mask=seg_result.mask
            )
            self.video_label.set_frame(display_frame)
            self.status_message.emit(
                f"Segmentation : pièce détectée ({seg_result.class_name}, "
                f"confiance {seg_result.confidence*100:.0f}%)."
            )
        else:
            self.video_label.set_frame(frame)
            self.status_message.emit(
                "Segmentation : aucune pièce détectée sur cette image."
            )

    def _update_frame(self):
        if self.capture is None or self.is_frozen:
            return
        ok, frame = self.capture.read()
        if not ok:
            self.status_message.emit("Erreur de lecture caméra.")
            return

        self.last_frame = frame

        # Calcul échelle mm/px via ratio direct marqueurs ArUco
        mm_per_px, n_markers, display_frame = self.scale_estimator.process(frame)
        if mm_per_px is not None:
            self.analyzer.set_scale(mm_per_px)
            self.calib_status_label.setText(
                f"Echelle : {mm_per_px:.4f} mm/px  "
                f"({n_markers} marqueur{'s' if n_markers != 1 else ''})"
            )
            self.calib_status_label.setStyleSheet("color: #1D9E75; font-weight: 500;")
        else:
            self.calib_status_label.setText("Echelle : marqueurs non visibles")
            self.calib_status_label.setStyleSheet("color: #D85A30; font-weight: 500;")

        if self.segmentation_active and self.engine.is_loaded:
            seg_result = self.engine.segment(frame)
            self.last_segmentation = seg_result
            if seg_result is not None:
                display_frame = DimensionAnalyzer.draw_annotations(
                    display_frame, None, mask=seg_result.mask
                )

        self.video_label.set_frame(display_frame)

    # ------------------------------------------------------------------
    # Bouton : Charger un modèle YOLOv8-seg
    # ------------------------------------------------------------------
    def _load_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner un modèle YOLOv8-seg", "", "Modèle PyTorch (*.pt)"
        )
        if not path:
            return
        try:
            self.engine.load_model(path)
            self.model_status_label.setText(
                f"Modèle : {os.path.basename(path)}"
            )
            self.model_status_label.setStyleSheet("color: #1D9E75; font-weight: 500;")
            self.status_message.emit(f"Modèle chargé : {path}")
        except ImportError as e:
            QMessageBox.critical(self, "Dépendance manquante", str(e))
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Fichier introuvable", str(e))
        except Exception as e:
            QMessageBox.critical(
                self, "Erreur de chargement",
                f"Impossible de charger le modèle :\n{e}"
            )

    # ------------------------------------------------------------------
    # Bouton 3 : Activer la segmentation
    # ------------------------------------------------------------------
    def _toggle_segmentation(self):
        if self.btn_segment.isChecked():
            if not self.engine.is_loaded:
                QMessageBox.information(
                    self, "Aucun modèle chargé",
                    "Chargez d'abord un modèle YOLOv8-seg (.pt) avec le "
                    "bouton \"Charger un modèle\" avant d'activer la "
                    "segmentation."
                )
                self.btn_segment.setChecked(False)
                return
            self.segmentation_active = True
            self.btn_segment.setText("🧩 Segmentation active")

            # Mode image statique (pas de caméra live) : aucun timer ne va
            # appeler _update_frame automatiquement, donc on déclenche la
            # segmentation immédiatement sur l'image actuellement chargée.
            if self.capture is None and self.last_frame is not None:
                self._run_segmentation_on_frame(self.last_frame)
            else:
                self.status_message.emit("Segmentation activée.")
        else:
            self.segmentation_active = False
            self.btn_segment.setText("🧩 Activer la segmentation")
            self.status_message.emit("Segmentation désactivée.")

    # ------------------------------------------------------------------
    # Bouton 4 : Afficher les dimensions
    # ------------------------------------------------------------------
    def _compute_dimensions(self):
        frame = self.frozen_frame if self.is_frozen else self.last_frame
        if frame is None:
            QMessageBox.information(
                self, "Aucune image", "Démarrez la caméra ou chargez une image avant de mesurer."
            )
            return

        # Si pas de segmentation disponible mais un modèle est chargé et
        # une image est présente → lancer la segmentation automatiquement
        # (cas typique : image chargée depuis le disque sans avoir activé
        # la segmentation au préalable)
        if self.last_segmentation is None:
            if self.engine.is_loaded:
                self.status_message.emit(
                    "Segmentation automatique en cours sur l'image..."
                )
                seg_result = self.engine.segment(frame)
                if seg_result is None:
                    QMessageBox.information(
                        self, "Aucune pièce détectée",
                        "Le modèle n'a détecté aucune pièce dans l'image.\n\n"
                        "Conseils :\n"
                        "• Vérifier que la pièce est bien visible et bien éclairée\n"
                        "• Ajuster le seuil de confiance du modèle\n"
                        "• Vérifier que le modèle est entraîné pour ce type de pièce"
                    )
                    return
                self.last_segmentation = seg_result
                # Afficher le masque sur l'image
                display = DimensionAnalyzer.draw_annotations(
                    frame, None, mask=seg_result.mask
                )
                self.video_label.set_frame(display)
            else:
                QMessageBox.information(
                    self, "Aucune segmentation",
                    "Aucune pièce segmentée. Deux options :\n\n"
                    "1. Charger un modèle YOLOv8-seg (.pt) puis cliquer\n"
                    "   'Afficher les dimensions' — la segmentation se\n"
                    "   lance automatiquement.\n\n"
                    "2. Activer la segmentation avant de charger l'image."
                )
                return

        if not self.analyzer.is_calibrated:
            QMessageBox.warning(
                self, "Échelle non définie",
                "Aucune calibration chargée. Effectuez d'abord la "
                "calibration caméra (onglet Calibration)."
            )
            return

        seg = self.last_segmentation
        measurement = self.analyzer.analyze(
            seg.mask, piece_name=seg.class_name, confidence=seg.confidence
        )
        if measurement is None:
            self.status_message.emit("Aucun contour exploitable dans le masque.")
            return

        self.last_measurement = measurement
        self._update_info_panel(measurement)

        annotated = DimensionAnalyzer.draw_annotations(frame, measurement, seg.mask)
        self.video_label.set_frame(annotated)
        self.status_message.emit(
            f"Dimensions calculées : L={measurement.length_mm:.1f}mm, "
            f"l={measurement.width_mm:.1f}mm, A={measurement.area_mm2:.0f}mm²"
        )

    def _update_info_panel(self, measurement):
        self.info_labels["piece_name"].setText(measurement.piece_name or "—")
        self.info_labels["confidence"].setText(f"{measurement.confidence * 100:.1f} %")
        self.info_labels["length"].setText(f"{measurement.length_mm:.2f} mm")
        self.info_labels["width"].setText(f"{measurement.width_mm:.2f} mm")
        self.info_labels["area"].setText(f"{measurement.area_mm2:.1f} mm²")
        self.info_labels["timestamp"].setText(
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )

    # ------------------------------------------------------------------
    # Bouton 5 : Geler les mesures
    # ------------------------------------------------------------------
    def _toggle_freeze(self):
        if self.btn_freeze.isChecked():
            if self.last_frame is None:
                QMessageBox.information(
                    self, "Aucune image", "Démarrez la caméra avant de geler."
                )
                self.btn_freeze.setChecked(False)
                return
            self.frozen_frame = self.last_frame.copy()
            self.is_frozen = True
            self.btn_freeze.setText("❄ Dégeler")
            self.status_message.emit(
                "Image gelée. Les mesures affichées sont figées pour analyse."
            )
        else:
            self.is_frozen = False
            self.frozen_frame = None
            self.btn_freeze.setText("❄ Geler les mesures")
            self.status_message.emit("Image dégelée, flux vidéo repris.")

    # ------------------------------------------------------------------
    # Bouton 6 : Capturer le résultat
    # ------------------------------------------------------------------
    def _capture_result(self):
        frame = self.frozen_frame if self.is_frozen else self.last_frame
        if frame is None:
            QMessageBox.information(
                self, "Aucune image", "Démarrez la caméra avant de capturer."
            )
            return

        mask = self.last_segmentation.mask if self.last_segmentation else None
        annotated = DimensionAnalyzer.draw_annotations(
            frame, self.last_measurement, mask
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mesure_{timestamp}.png"
        filepath = os.path.join(MEASUREMENTS_DIR, filename)
        cv2.imwrite(filepath, annotated)

        if self.last_measurement is not None:
            self.measurement_history.append(self.last_measurement)
            item_text = (
                f"{filename} — L={self.last_measurement.length_mm:.1f}mm "
                f"l={self.last_measurement.width_mm:.1f}mm"
            )
            self.history_list.addItem(QListWidgetItem(item_text))
            self.history_group.setTitle(
                f"Historique des mesures ({len(self.measurement_history)})"
            )

        self.status_message.emit(f"Résultat capturé : {filepath}")

    # ------------------------------------------------------------------
    # Bouton 7 : Exporter les résultats
    # ------------------------------------------------------------------
    def _export_csv(self):
        if not self.measurement_history:
            QMessageBox.information(
                self, "Aucune mesure",
                "Capturez au moins un résultat avant d'exporter."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter les mesures (CSV)",
            os.path.join(MEASUREMENTS_DIR, "mesures.csv"), "CSV (*.csv)"
        )
        if path:
            MeasurementExporter.export_csv(self.measurement_history, path)
            self.status_message.emit(f"Mesures exportées (CSV) : {path}")

    def _export_json(self):
        if not self.measurement_history:
            QMessageBox.information(
                self, "Aucune mesure",
                "Capturez au moins un résultat avant d'exporter."
            )
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter les mesures (JSON)",
            os.path.join(MEASUREMENTS_DIR, "mesures.json"), "JSON (*.json)"
        )
        if path:
            MeasurementExporter.export_json(self.measurement_history, path)
            self.status_message.emit(f"Mesures exportées (JSON) : {path}")

    # ------------------------------------------------------------------
    # Bouton 8 : Comparer avec le fichier STL
    # ------------------------------------------------------------------
    def _compare_with_stl(self):
        if self.last_measurement is None:
            QMessageBox.information(
                self, "Aucune mesure",
                "Calculez d'abord les dimensions (bouton \"Afficher les "
                "dimensions\") avant de comparer avec un fichier STL."
            )
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner le fichier STL de référence", "", "STL (*.stl)"
        )
        if not path:
            return

        try:
            self.stl_comparator.load_stl(path)
            result = self.stl_comparator.compare(self.last_measurement)
            self.last_stl_comparison = result

            verdict = (
                "✓ Conforme" if abs(result.error_length_pct) < 2
                and abs(result.error_width_pct) < 2
                else "⚠ Écart significatif"
            )
            self.stl_result_label.setText(
                f"Fichier : {result.stl_file_name}\n"
                f"Longueur : mesurée {result.measured_length_mm:.2f}mm vs "
                f"théorique {result.theoretical_length_mm:.2f}mm "
                f"(écart {result.error_length_mm:+.2f}mm, {result.error_length_pct:+.1f}%)\n"
                f"Largeur : mesurée {result.measured_width_mm:.2f}mm vs "
                f"théorique {result.theoretical_width_mm:.2f}mm "
                f"(écart {result.error_width_mm:+.2f}mm, {result.error_width_pct:+.1f}%)\n"
                f"{verdict}"
            )
            self.stl_result_label.setStyleSheet(
                "color: #1D9E75; font-size: 11px;" if "✓" in verdict
                else "color: #D85A30; font-size: 11px;"
            )
            self.status_message.emit(
                f"Comparaison STL effectuée : erreur longueur "
                f"{result.error_length_pct:+.1f}%, largeur {result.error_width_pct:+.1f}%"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Erreur de comparaison STL", f"{e}"
            )

    # ------------------------------------------------------------------
    # Bouton 9 : Réinitialiser
    # ------------------------------------------------------------------
    def _reset_all(self):
        reply = QMessageBox.question(
            self, "Confirmer la réinitialisation",
            "Effacer toutes les mesures et résultats de cette session ?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.last_segmentation = None
        self.last_measurement = None
        self.last_stl_comparison = None
        self.measurement_history.clear()
        self.is_frozen = False
        self.frozen_frame = None

        self.btn_freeze.setChecked(False)
        self.btn_freeze.setText("❄ Geler les mesures")
        self.btn_segment.setChecked(False)
        self.btn_segment.setText("🧩 Activer la segmentation")
        self.segmentation_active = False

        for lbl in self.info_labels.values():
            lbl.setText("—")
        self.stl_result_label.setText(
            "Chargez un fichier STL pour comparer les dimensions "
            "théoriques aux dimensions mesurées."
        )
        self.stl_result_label.setStyleSheet("font-size: 11px;")
        self.history_list.clear()
        self.history_group.setTitle("Historique des mesures (0)")

        self.status_message.emit("Session réinitialisée.")

    # ------------------------------------------------------------------
    # Bouton : Générer le rapport PDF
    # ------------------------------------------------------------------
    def _generate_report(self):
        """Génère un rapport PDF professionnel avec calibration,
        mesures, écarts vs STL, et recommandations techniques complètes."""

        if self.last_measurement is None:
            QMessageBox.information(
                self, "Aucune mesure disponible",
                "Effectuez d'abord une mesure (bouton \"Afficher les "
                "dimensions\") avant de générer le rapport."
            )
            return

        # Choix du chemin de sauvegarde
        from datetime import datetime as _dt
        default_name = (
            f"rapport_inspection_"
            f"{_dt.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Enregistrer le rapport PDF",
            os.path.join(MEASUREMENTS_DIR, default_name),
            "PDF (*.pdf)",
        )
        if not path:
            return

        self.status_message.emit("Génération du rapport PDF en cours...")

        try:
            gen = ReportGenerator()

            # Récupérer la calibration depuis le fichier YAML si disponible
            calib_result = getattr(self, "_last_calib_result", None)

            gen.generate(
                output_path=path,
                measurement=self.last_measurement,
                stl_comparison=self.last_stl_comparison,
                calibration_result=calib_result,
                working_distance_mm=self._working_distance_mm,
                piece_name=self.last_measurement.piece_name or "—",
                model_name=os.path.basename(
                    self.engine.model_path
                ) if self.engine.model_path else "YOLOv8-seg",
            )

            self.status_message.emit(f"Rapport PDF généré : {path}")
            QMessageBox.information(
                self, "Rapport généré",
                f"Le rapport PDF a été sauvegardé :\n{path}"
            )

        except Exception as e:
            QMessageBox.critical(
                self, "Erreur de génération",
                f"Impossible de générer le rapport PDF :\n{e}"
            )
            self.status_message.emit(f"Erreur rapport PDF : {e}")

    # ------------------------------------------------------------------
    # Mode Image : charger une image depuis le disque (alternative caméra)
    # ------------------------------------------------------------------
    def _load_image_from_file(self):
        """
        Charge une image depuis le disque (photo téléphone, fichier PNG/JPG…)
        et l'affiche dans la zone vidéo exactement comme un frame caméra.

        Une fois chargée, tous les boutons existants fonctionnent identiquement :
        segmentation, afficher les dimensions, geler, capturer, STL, rapport.
        Le mode image et le mode caméra live sont mutuellement exclusifs :
        charger une image arrête automatiquement la caméra si elle tournait.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Charger une image à analyser",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp)",
        )
        if not path:
            return

        frame = cv2.imread(path)
        if frame is None:
            QMessageBox.warning(
                self, "Erreur de lecture",
                f"Impossible de lire l'image :\n{path}\n\n"
                "Vérifiez que le format est supporté (JPG, PNG, BMP, TIFF)."
            )
            return

        # Arrêter la caméra live si elle tourne (les deux modes s'excluent)
        if self.capture is not None:
            self._stop_camera()

        # Stocker comme dernier frame — exactement comme _update_frame le ferait
        self.last_frame = frame
        self.is_frozen = True          # figer : pas de caméra qui écraserait l'image
        self.frozen_frame = frame.copy()

        # Mettre à jour le bouton geler visuellement pour cohérence
        self.btn_freeze.setChecked(True)
        self.btn_freeze.setText("❄ Dégeler")

        # Calcul échelle mm/px via ratio direct marqueurs ArUco dans l'image
        mm_per_px, n_markers, display_frame = self.scale_estimator.process(frame)
        if mm_per_px is not None:
            self.analyzer.set_scale(mm_per_px)
            self.calib_status_label.setText(
                f"Echelle : {mm_per_px:.4f} mm/px  "
                f"({n_markers} marqueur{'s' if n_markers != 1 else ''})"
            )
            self.calib_status_label.setStyleSheet("color: #1D9E75; font-weight: 500;")
        else:
            self.calib_status_label.setText("Echelle : marqueurs non visibles dans cette image")
            self.calib_status_label.setStyleSheet("color: #D85A30; font-weight: 500;")

        self.video_label.set_frame(display_frame)

        # Réinitialiser la segmentation précédente (nouvelle image = nouveau contexte)
        self.last_segmentation = None

        # Si la segmentation est déjà active et un modèle est chargé, lancer
        # directement la détection sur l'image qu'on vient de charger.
        if self.segmentation_active and self.engine.is_loaded:
            self._run_segmentation_on_frame(frame)
        else:
            self.status_message.emit(
                f"Image chargée : {os.path.basename(path)} "
                f"({frame.shape[1]}×{frame.shape[0]} px) — "
                "Activez la segmentation ou cliquez 'Afficher les dimensions'."
            )

    # ------------------------------------------------------------------
    def release_camera(self):
        """À appeler depuis la fenêtre principale lors de la fermeture."""
        if self.capture is not None:
            self.timer.stop()
            self.capture.release()
            self.capture = None
