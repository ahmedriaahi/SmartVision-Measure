"""
Gestion des thèmes visuels (clair / sombre) de l'application.

Ce module est PUREMENT cosmétique : il ne touche à aucune logique
fonctionnelle. Il expose une seule fonction publique `apply_theme(app, mode)`
qui écrase la palette Qt de l'application avec les couleurs du thème choisi.

Thème clair  : blanc/gris clair, accents vert industriel, ambiance pro
Thème sombre : gris anthracite, accents bleu/cyan, ambiance station industrielle

Usage :
    from theme_manager import apply_theme, LIGHT, DARK
    apply_theme(app, DARK)
"""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

LIGHT = "light"
DARK  = "dark"

# ---------------------------------------------------------------------------
# Définition des deux palettes
# ---------------------------------------------------------------------------

def _make_light_palette():
    """
    Thème clair — blanc/gris clair, accents vert industriel #1D9E75.
    """
    p = QPalette()

    # Fenêtre et surfaces
    p.setColor(QPalette.Window,          QColor("#F4F4F2"))
    p.setColor(QPalette.WindowText,      QColor("#1A1A1A"))
    p.setColor(QPalette.Base,            QColor("#FFFFFF"))
    p.setColor(QPalette.AlternateBase,   QColor("#EAEAE6"))

    # Texte
    p.setColor(QPalette.Text,            QColor("#1A1A1A"))
    p.setColor(QPalette.BrightText,      QColor("#000000"))
    p.setColor(QPalette.PlaceholderText, QColor("#AAAAAA"))

    # Boutons
    p.setColor(QPalette.Button,          QColor("#E0E0DA"))
    p.setColor(QPalette.ButtonText,      QColor("#1A1A1A"))

    # Sélection — accent vert industriel
    p.setColor(QPalette.Highlight,       QColor("#1D9E75"))
    p.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))

    # Liens
    p.setColor(QPalette.Link,            QColor("#0F6E56"))
    p.setColor(QPalette.LinkVisited,     QColor("#085041"))

    # Ombres / reflets
    p.setColor(QPalette.Light,           QColor("#FFFFFF"))
    p.setColor(QPalette.Midlight,        QColor("#EEEEEA"))
    p.setColor(QPalette.Mid,             QColor("#C0C0BC"))
    p.setColor(QPalette.Dark,            QColor("#909088"))
    p.setColor(QPalette.Shadow,          QColor("#606060"))

    # États désactivés
    p.setColor(QPalette.Disabled, QPalette.WindowText,  QColor("#AAAAAA"))
    p.setColor(QPalette.Disabled, QPalette.Text,        QColor("#AAAAAA"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText,  QColor("#AAAAAA"))
    p.setColor(QPalette.Disabled, QPalette.Highlight,   QColor("#C0C0BC"))
    p.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor("#FFFFFF"))

    return p


def _make_dark_palette():
    """
    Thème sombre — gris anthracite, accents bleu #378ADD, ambiance
    station d'inspection industrielle (proche du screenshot actuel de
    l'application en mode sombre Ubuntu).
    """
    p = QPalette()

    # Fenêtre et surfaces
    p.setColor(QPalette.Window,          QColor("#2B2B2B"))
    p.setColor(QPalette.WindowText,      QColor("#ECECEC"))
    p.setColor(QPalette.Base,            QColor("#1E1E1E"))
    p.setColor(QPalette.AlternateBase,   QColor("#252525"))

    # Texte
    p.setColor(QPalette.Text,            QColor("#ECECEC"))
    p.setColor(QPalette.BrightText,      QColor("#FFFFFF"))
    p.setColor(QPalette.PlaceholderText, QColor("#666666"))

    # Boutons
    p.setColor(QPalette.Button,          QColor("#3A3A3A"))
    p.setColor(QPalette.ButtonText,      QColor("#ECECEC"))

    # Sélection — accent bleu industriel
    p.setColor(QPalette.Highlight,       QColor("#378ADD"))
    p.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))

    # Liens
    p.setColor(QPalette.Link,            QColor("#85B7EB"))
    p.setColor(QPalette.LinkVisited,     QColor("#B5D4F4"))

    # Ombres / reflets
    p.setColor(QPalette.Light,           QColor("#555555"))
    p.setColor(QPalette.Midlight,        QColor("#444444"))
    p.setColor(QPalette.Mid,             QColor("#383838"))
    p.setColor(QPalette.Dark,            QColor("#252525"))
    p.setColor(QPalette.Shadow,          QColor("#111111"))

    # États désactivés
    p.setColor(QPalette.Disabled, QPalette.WindowText,  QColor("#666666"))
    p.setColor(QPalette.Disabled, QPalette.Text,        QColor("#666666"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText,  QColor("#666666"))
    p.setColor(QPalette.Disabled, QPalette.Highlight,   QColor("#444444"))
    p.setColor(QPalette.Disabled, QPalette.HighlightedText, QColor("#999999"))

    return p


# Feuille de style complémentaire au QPalette pour quelques widgets
# spécifiques que Qt/Fusion ne colore pas entièrement via la palette seule
# (barres de statut, onglets actifs, groupbox, scrollbar).
_STYLESHEET_LIGHT = """
QMainWindow, QDialog { background: #F4F4F2; }

QTabBar::tab {
    background: #E0E0DA;
    color: #444444;
    padding: 7px 18px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #1A1A1A;
    font-weight: 500;
    border-bottom: 2px solid #1D9E75;
}
QTabBar::tab:hover:!selected { background: #EAEAE6; }

QGroupBox {
    font-weight: 500;
    border: 1px solid #C8C8C4;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 6px;
    color: #1D9E75;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

QStatusBar {
    background: #E8E8E4;
    color: #555555;
    border-top: 1px solid #C8C8C4;
    font-size: 12px;
}

QScrollBar:vertical {
    background: #EAEAE6;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #BBBBBB;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #1D9E75; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QToolBar {
    background: #EAEAE6;
    border-bottom: 1px solid #C8C8C4;
    spacing: 6px;
    padding: 3px 8px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 13px;
    color: #1A1A1A;
}
QToolButton:hover {
    background: #D8D8D4;
    border-color: #BBBBBB;
}
QToolButton:pressed { background: #C8C8C4; }

QPushButton {
    border: 1px solid #C8C8C4;
    border-radius: 5px;
    padding: 5px 12px;
    background: #E8E8E4;
    color: #1A1A1A;
}
QPushButton:hover {
    background: #D8D8D4;
    border-color: #AAAAAA;
}
QPushButton:pressed { background: #C8C8C4; }
QPushButton:disabled { color: #AAAAAA; background: #EEEEEC; border-color: #DDDDDA; }

QListWidget {
    border: 1px solid #C8C8C4;
    border-radius: 5px;
    background: #FFFFFF;
}
QListWidget::item:selected {
    background: #1D9E75;
    color: #FFFFFF;
    border-radius: 3px;
}

QTextEdit {
    border: 1px solid #C8C8C4;
    border-radius: 5px;
    background: #FFFFFF;
}

QComboBox {
    border: 1px solid #C8C8C4;
    border-radius: 5px;
    padding: 4px 8px;
    background: #FFFFFF;
}
QComboBox::drop-down { border: none; width: 20px; }
"""

_STYLESHEET_DARK = """
QMainWindow, QDialog { background: #2B2B2B; }

QTabBar::tab {
    background: #383838;
    color: #AAAAAA;
    padding: 7px 18px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #2B2B2B;
    color: #ECECEC;
    font-weight: 500;
    border-bottom: 2px solid #378ADD;
}
QTabBar::tab:hover:!selected { background: #404040; }

QGroupBox {
    font-weight: 500;
    border: 1px solid #444444;
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 6px;
    color: #378ADD;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

QStatusBar {
    background: #242424;
    color: #888888;
    border-top: 1px solid #444444;
    font-size: 12px;
}

QScrollBar:vertical {
    background: #333333;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #555555;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #378ADD; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QToolBar {
    background: #242424;
    border-bottom: 1px solid #444444;
    spacing: 6px;
    padding: 3px 8px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 13px;
    color: #ECECEC;
}
QToolButton:hover {
    background: #3A3A3A;
    border-color: #555555;
}
QToolButton:pressed { background: #444444; }

QPushButton {
    border: 1px solid #505050;
    border-radius: 5px;
    padding: 5px 12px;
    background: #3A3A3A;
    color: #ECECEC;
}
QPushButton:hover {
    background: #444444;
    border-color: #666666;
}
QPushButton:pressed { background: #505050; }
QPushButton:disabled { color: #666666; background: #2E2E2E; border-color: #3A3A3A; }

QListWidget {
    border: 1px solid #444444;
    border-radius: 5px;
    background: #1E1E1E;
}
QListWidget::item:selected {
    background: #378ADD;
    color: #FFFFFF;
    border-radius: 3px;
}

QTextEdit {
    border: 1px solid #444444;
    border-radius: 5px;
    background: #1E1E1E;
}

QComboBox {
    border: 1px solid #505050;
    border-radius: 5px;
    padding: 4px 8px;
    background: #3A3A3A;
    color: #ECECEC;
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background: #3A3A3A;
    color: #ECECEC;
    selection-background-color: #378ADD;
}
"""


# ---------------------------------------------------------------------------
# Fonction publique
# ---------------------------------------------------------------------------

def apply_theme(app: QApplication, mode: str):
    """
    Applique le thème `mode` (LIGHT ou DARK) à toute l'application.

    Aucun impact sur la logique fonctionnelle — pure cosmétique.
    """
    app.setStyle("Fusion")

    if mode == DARK:
        app.setPalette(_make_dark_palette())
        app.setStyleSheet(_STYLESHEET_DARK)
    else:
        app.setPalette(_make_light_palette())
        app.setStyleSheet(_STYLESHEET_LIGHT)
