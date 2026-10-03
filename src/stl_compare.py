"""
Module de comparaison avec un fichier STL de référence.

Charge un fichier STL (le modèle 3D théorique de la pièce imprimée),
en extrait les dimensions théoriques (bounding box), et les compare aux
dimensions mesurées par segmentation + findContours pour calculer l'erreur
dimensionnelle — l'objectif final du pipeline de calibration post-prod.
"""

import os
from dataclasses import dataclass

import numpy as np

try:
    from stl import mesh as stl_mesh
    STL_AVAILABLE = True
except ImportError:
    STL_AVAILABLE = False


@dataclass
class STLDimensions:
    """Dimensions théoriques extraites d'un fichier STL."""

    length_mm: float   # plus grande dimension du bounding box (X/Y/Z)
    width_mm: float    # deuxième plus grande dimension
    height_mm: float    # plus petite dimension
    volume_mm3: float
    file_name: str


@dataclass
class STLComparisonResult:
    """Résultat de la comparaison mesure réelle vs théorique STL."""

    measured_length_mm: float
    measured_width_mm: float
    theoretical_length_mm: float
    theoretical_width_mm: float
    error_length_mm: float
    error_width_mm: float
    error_length_pct: float
    error_width_pct: float
    stl_file_name: str

    def to_dict(self):
        return {
            "measured_length_mm": round(self.measured_length_mm, 3),
            "measured_width_mm": round(self.measured_width_mm, 3),
            "theoretical_length_mm": round(self.theoretical_length_mm, 3),
            "theoretical_width_mm": round(self.theoretical_width_mm, 3),
            "error_length_mm": round(self.error_length_mm, 3),
            "error_width_mm": round(self.error_width_mm, 3),
            "error_length_pct": round(self.error_length_pct, 2),
            "error_width_pct": round(self.error_width_pct, 2),
            "stl_file_name": self.stl_file_name,
        }


class STLComparator:
    """
    Charge un fichier STL et compare ses dimensions théoriques à une
    mesure réelle (issue de DimensionAnalyzer.analyze()).

    Hypothèse de convention : le fichier STL est exporté en millimètres,
    convention la plus courante pour les trancheurs d'impression 3D
    (Cura, PrusaSlicer...). Si le STL source utilise une autre unité,
    appliquer `unit_scale` en conséquence (ex: 0.001 si le STL est en
    micromètres, 1000 s'il est en mètres).
    """

    def __init__(self):
        if not STL_AVAILABLE:
            raise ImportError(
                "Le paquet 'numpy-stl' n'est pas installé. "
                "Installez-le avec : pip install numpy-stl"
            )
        self._theoretical = None

    def load_stl(self, path, unit_scale=1.0):
        """
        Charge un fichier STL et calcule ses dimensions théoriques.

        Lève FileNotFoundError si le fichier n'existe pas, et ValueError
        si le fichier ne peut pas être interprété comme un STL valide.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"Fichier STL introuvable : {path}")

        try:
            m = stl_mesh.Mesh.from_file(path)
        except Exception as e:
            raise ValueError(f"Impossible de lire le fichier STL : {e}") from e

        dims = (m.max_ - m.min_) * unit_scale  # [dx, dy, dz] en mm
        dims_sorted = sorted(dims, reverse=True)

        volume_mm3 = self._compute_volume(m) * (unit_scale ** 3)

        self._theoretical = STLDimensions(
            length_mm=float(dims_sorted[0]),
            width_mm=float(dims_sorted[1]),
            height_mm=float(dims_sorted[2]),
            volume_mm3=float(abs(volume_mm3)),
            file_name=os.path.basename(path),
        )
        return self._theoretical

    @staticmethod
    def _compute_volume(m):
        """Volume signé d'un maillage triangulaire fermé (méthode des tétraèdres
        depuis l'origine), utile pour une cohérence visuelle dans le rapport."""
        v0, v1, v2 = m.v0, m.v1, m.v2
        # volume du tétraèdre (origine, v0, v1, v2) = (v0 . (v1 x v2)) / 6
        cross = np.cross(v1, v2)
        vol = np.sum(np.einsum("ij,ij->i", v0, cross)) / 6.0
        return vol

    @property
    def theoretical_dimensions(self):
        return self._theoretical

    def compare(self, measurement):
        """
        Compare une mesure réelle (DimensionMeasurement de
        segmentation_engine.py) aux dimensions théoriques du STL chargé.

        Lève ValueError si aucun STL n'a été chargé au préalable.
        """
        if self._theoretical is None:
            raise ValueError("Aucun fichier STL chargé. Appelez load_stl() d'abord.")

        t = self._theoretical
        err_l = measurement.length_mm - t.length_mm
        err_w = measurement.width_mm - t.width_mm
        err_l_pct = (err_l / t.length_mm * 100) if t.length_mm else 0.0
        err_w_pct = (err_w / t.width_mm * 100) if t.width_mm else 0.0

        return STLComparisonResult(
            measured_length_mm=measurement.length_mm,
            measured_width_mm=measurement.width_mm,
            theoretical_length_mm=t.length_mm,
            theoretical_width_mm=t.width_mm,
            error_length_mm=err_l,
            error_width_mm=err_w,
            error_length_pct=err_l_pct,
            error_width_pct=err_w_pct,
            stl_file_name=t.file_name,
        )
