"""
Widget Qt encapsulant un graphique matplotlib pour visualiser
l'erreur de reprojection par image après calibration.

Séparé du reste de l'UI pour rester réutilisable (ex: réutilisable
plus tard pour d'autres graphiques qualité dans le pipeline complet).
"""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QWidget, QVBoxLayout


class ReprojectionErrorChart(QWidget):
    """Graphique à barres : erreur de reprojection RMS (px) par image."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.figure = Figure(figsize=(5, 3), tight_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.ax = self.figure.add_subplot(111)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

        self._draw_empty()

    def _draw_empty(self):
        self.ax.clear()
        self.ax.set_title("Erreur de reprojection par image", fontsize=10)
        self.ax.set_xlabel("Image", fontsize=9)
        self.ax.set_ylabel("Erreur RMS (pixels)", fontsize=9)
        self.ax.text(
            0.5,
            0.5,
            "En attente de calibration...",
            transform=self.ax.transAxes,
            ha="center",
            va="center",
            fontsize=9,
            color="gray",
        )
        self.canvas.draw()

    def update_chart(self, image_names, per_image_errors, overall_rms):
        """
        Met à jour le graphique avec les erreurs par image.

        Les barres au-dessus d'un seuil critique (> 1.5x la moyenne)
        sont colorées en rouge pour permettre d'identifier rapidement
        les images de mauvaise qualité à retirer.
        """
        self.ax.clear()

        n = len(per_image_errors)
        x = list(range(1, n + 1))
        mean_error = sum(per_image_errors) / n if n else 0
        threshold = mean_error * 1.5

        colors = [
            "#D85A30" if e > threshold else "#1D9E75" for e in per_image_errors
        ]

        self.ax.bar(x, per_image_errors, color=colors, width=0.6)
        self.ax.axhline(
            overall_rms,
            color="#185FA5",
            linestyle="--",
            linewidth=1.2,
            label=f"RMS global = {overall_rms:.3f} px",
        )

        self.ax.set_title("Erreur de reprojection par image", fontsize=10)
        self.ax.set_xlabel("Image", fontsize=9)
        self.ax.set_ylabel("Erreur RMS (pixels)", fontsize=9)
        self.ax.set_xticks(x)
        self.ax.tick_params(axis="both", labelsize=8)
        self.ax.legend(fontsize=8, loc="upper right")
        self.ax.grid(axis="y", alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw()

    def clear(self):
        self._draw_empty()
