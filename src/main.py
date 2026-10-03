"""
Application d'inspection de pièces imprimées 3D — Station fixe industrielle.
AI Post-Production Calibration Tool.

Point d'entrée principal : héberge les deux onglets de l'application dans
un QTabWidget commun, avec une barre de statut partagée.

    Onglet 1 — Calibration : calibration caméra par mire ChArUco
    Onglet 2 — Modèle      : segmentation YOLOv8-seg, mesure dimensionnelle,
                              comparaison STL

Lancement :
    python main.py
"""

import os
import sys

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QStatusBar, QToolBar
)
from PySide6.QtGui import QAction
from PySide6.QtCore import Qt

sys.path.insert(0, os.path.dirname(__file__))
from calibration_tab import CalibrationTab
from model_tab import ModelTab
from theme_manager import apply_theme, LIGHT, DARK


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(
            "Inspection de pièces imprimées 3D — ChArUco + YOLOv8-Seg"
        )
        self.resize(1280, 860)

        # Thème par défaut : sombre (ambiance station industrielle)
        self._current_theme = DARK

        # ── Toolbar avec bouton toggle thème ──────────────────────────────
        toolbar = QToolBar("Barre principale")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        # Espaceur pour pousser le bouton tout à droite
        from PySide6.QtWidgets import QWidget
        spacer = QWidget()
        spacer.setSizePolicy(
            spacer.sizePolicy().horizontalPolicy(),
            spacer.sizePolicy().verticalPolicy(),
        )
        from PySide6.QtWidgets import QSizePolicy
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)

        self._theme_action = QAction("", self)
        self._theme_action.setToolTip("Basculer entre le mode sombre et le mode clair")
        self._theme_action.triggered.connect(self._toggle_theme)
        toolbar.addAction(self._theme_action)
        self._update_theme_icon()

        # ── Onglets ────────────────────────────────────────────────────────
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.calibration_tab = CalibrationTab()
        self.model_tab = ModelTab()

        self.tabs.addTab(self.calibration_tab, "🎯 Calibration")
        self.tabs.addTab(self.model_tab, "🧩 Modèle")

        # ── Barre de statut ────────────────────────────────────────────────
        self.setStatusBar(QStatusBar())

        self.calibration_tab.status_message.connect(self.statusBar().showMessage)
        self.model_tab.status_message.connect(self.statusBar().showMessage)

        self.calibration_tab.calibration_exported.connect(
            self.model_tab.on_calibration_exported
        )


        self.statusBar().showMessage(
            "Bienvenue. Commencez par l'onglet Calibration si ce n'est pas "
            "déjà fait, puis passez à l'onglet Modèle pour l'inspection."
        )

    # ── Toggle thème ──────────────────────────────────────────────────────

    def _toggle_theme(self):
        self._current_theme = LIGHT if self._current_theme == DARK else DARK
        apply_theme(QApplication.instance(), self._current_theme)
        self._update_theme_icon()

    def _update_theme_icon(self):
        if self._current_theme == DARK:
            self._theme_action.setText("☀️  Mode clair")
        else:
            self._theme_action.setText("🌙  Mode sombre")

    # ── Fermeture ─────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self.calibration_tab.release_camera()
        self.model_tab.release_camera()
        event.accept()


def main():
    app = QApplication(sys.argv)

    # Appliquer le thème sombre dès le démarrage (avant de créer la fenêtre,
    # pour éviter tout flash visuel du thème système par défaut)
    apply_theme(app, DARK)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
