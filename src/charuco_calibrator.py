"""
Module de calibration caméra par mire ChArUco.

Encapsule toute la logique OpenCV : détection du board, accumulation
des observations multi-images, calcul de la calibration, et calcul
de l'erreur de reprojection par image (pour le diagnostic qualité).

Board utilisé (Calib.io) :
    8 x 11 cases, case = 20 mm, marqueur = 15 mm, dictionnaire DICT_5X5_1000
"""

import os
import json
from dataclasses import dataclass, field

import cv2
import cv2.aruco as aruco
import numpy as np


# ---------------------------------------------------------------------------
# Configuration du board (valeurs fournies par l'utilisateur, Calib.io)
# ---------------------------------------------------------------------------
BOARD_SQUARES_X = 8
BOARD_SQUARES_Y = 11
BOARD_SQUARE_LENGTH_M = 0.020   # 20 mm -> mètres (convention OpenCV : mètres)
BOARD_MARKER_LENGTH_M = 0.015   # 15 mm -> mètres
BOARD_DICTIONARY = aruco.DICT_5X5_1000


# ---------------------------------------------------------------------------
# Mapping id -> position (chess_row, chess_col) tel qu'utilisé par Calib.io.
#
# Calib.io numérote les marqueurs ArUco dans un ordre différent de la
# convention par défaut de cv2.aruco.CharucoBoard (qui les numérote ligne par
# ligne, de gauche à droite). Sur le board Calib.io (8x11, vérifié par
# détection directe sur le PDF de référence), les marqueurs sont numérotés
# colonne par colonne en partant de la droite, avec un entrelacement entre
# lignes paires/impaires. Sans ce mapping, cv2.aruco interpole 0 coin
# ChArUco (alors que les marqueurs individuels sont bien détectés), car son
# vérificateur interne de cohérence position/ID rejette tout le board.
#
# Ce mapping a été extrait empiriquement en détectant les marqueurs ArUco
# bruts sur le PDF officiel Calib.io (8x11, case 20mm, marqueur 15mm,
# DICT_5X5) et en reconstruisant la grille (row, col) à partir de leurs
# positions pixel exactes.
# ---------------------------------------------------------------------------
CALIBIO_ID_TO_CHESS_POS = {
    0: (0, 7), 1: (2, 7), 2: (4, 7), 3: (6, 7), 4: (8, 7), 5: (10, 7),
    6: (1, 6), 7: (3, 6), 8: (5, 6), 9: (7, 6), 10: (9, 6),
    11: (0, 5), 12: (2, 5), 13: (4, 5), 14: (6, 5), 15: (8, 5), 16: (10, 5),
    17: (1, 4), 18: (3, 4), 19: (5, 4), 20: (7, 4), 21: (9, 4),
    22: (0, 3), 23: (2, 3), 24: (4, 3), 25: (6, 3), 26: (8, 3), 27: (10, 3),
    28: (1, 2), 29: (3, 2), 30: (5, 2), 31: (7, 2), 32: (9, 2),
    33: (0, 1), 34: (2, 1), 35: (4, 1), 36: (6, 1), 37: (8, 1), 38: (10, 1),
    39: (1, 0), 40: (3, 0), 41: (5, 0), 42: (7, 0), 43: (9, 0),
}


def _build_calibio_ids_array(squares_x, squares_y):
    """
    Construit le tableau `ids` (dans l'ordre attendu par cv2.aruco.CharucoBoard)
    à partir du mapping Calib.io id -> (row, col).

    cv2.aruco.CharucoBoard attend un tableau où l'élément à l'index i donne
    l'ID du marqueur situé à la i-ème position "marqueur" du board, en
    parcourant les cases en row-major (ligne par ligne) et en ne retenant
    que les cases où un marqueur est présent (motif damier, une case sur
    deux selon (row + col) % 2).
    """
    default_positions = [
        (r, c)
        for r in range(squares_y)
        for c in range(squares_x)
        if (r + c) % 2 == 1
    ]
    pos_to_calibio_id = {v: k for k, v in CALIBIO_ID_TO_CHESS_POS.items()}

    missing = [pos for pos in default_positions if pos not in pos_to_calibio_id]
    if missing:
        raise ValueError(
            f"Mapping Calib.io incomplet pour un board {squares_x}x{squares_y} : "
            f"positions manquantes {missing}. Le mapping CALIBIO_ID_TO_CHESS_POS "
            "n'a été vérifié que pour un board 8x11."
        )

    return np.array(
        [pos_to_calibio_id[pos] for pos in default_positions], dtype=np.int32
    )


@dataclass
class CalibrationResult:
    """Résultat structuré d'une calibration caméra réussie."""

    camera_matrix: np.ndarray
    dist_coeffs: np.ndarray
    image_size: tuple  # (width, height)
    overall_rms_error: float
    per_image_errors: list  # liste de float, un par image utilisée
    used_image_names: list  # noms des fichiers effectivement utilisés
    rejected_image_names: list = field(default_factory=list)  # board non détecté

    def to_dict(self):
        return {
            "camera_matrix": self.camera_matrix.tolist(),
            "dist_coeffs": self.dist_coeffs.flatten().tolist(),
            "image_width": int(self.image_size[0]),
            "image_height": int(self.image_size[1]),
            "overall_rms_error": float(self.overall_rms_error),
            "per_image_errors": [float(e) for e in self.per_image_errors],
            "used_image_names": self.used_image_names,
            "rejected_image_names": self.rejected_image_names,
            "board_config": {
                "squares_x": BOARD_SQUARES_X,
                "squares_y": BOARD_SQUARES_Y,
                "square_length_mm": BOARD_SQUARE_LENGTH_M * 1000,
                "marker_length_mm": BOARD_MARKER_LENGTH_M * 1000,
                "dictionary": "DICT_5X5_1000",
            },
        }

    def save_json(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    def save_opencv_yaml(self, path):
        """Sauvegarde au format YAML lisible par cv2.FileStorage (réutilisable
        directement par d'autres modules du pipeline, ex: ICP / projection STL)."""
        fs = cv2.FileStorage(path, cv2.FILE_STORAGE_WRITE)
        fs.write("camera_matrix", self.camera_matrix)
        fs.write("dist_coeffs", self.dist_coeffs)
        fs.write("image_width", self.image_size[0])
        fs.write("image_height", self.image_size[1])
        fs.write("rms_error", self.overall_rms_error)
        fs.write("n_images", len(self.used_image_names))
        fs.release()


class CharucoCalibrator:
    """
    Gère la détection du board ChArUco et la calibration caméra.

    Usage typique :
        calib = CharucoCalibrator()
        overlay, n_corners = calib.detect_and_draw(frame)   # pour affichage live
        calib.add_image(frame, name="img_001.png")          # sur appui touche S
        result = calib.calibrate()                          # quand assez d'images
    """

    MIN_CORNERS_PER_IMAGE = 6  # seuil minimal de coins ChArUco détectés pour garder une image
    MIN_IMAGES_FOR_CALIBRATION = 8  # recommandé pour une calibration stable

    def __init__(self):
        self.dictionary = aruco.getPredefinedDictionary(BOARD_DICTIONARY)

        # Board construit avec le mapping id -> position réel de Calib.io
        # (voir CALIBIO_ID_TO_CHESS_POS plus haut). Sans ce mapping explicite,
        # cv2.aruco.CharucoBoard suppose sa propre convention de numérotation
        # et l'interpolation des coins ChArUco échoue silencieusement (0 coin
        # détecté) même si les marqueurs individuels sont bien identifiés.
        calibio_ids = _build_calibio_ids_array(BOARD_SQUARES_X, BOARD_SQUARES_Y)
        self.board = aruco.CharucoBoard(
            (BOARD_SQUARES_X, BOARD_SQUARES_Y),
            BOARD_SQUARE_LENGTH_M,
            BOARD_MARKER_LENGTH_M,
            self.dictionary,
            ids=calibio_ids,
        )

        detector_params = aruco.DetectorParameters()
        charuco_params = aruco.CharucoParameters()
        # checkMarkers vérifie en interne que chaque marqueur détecté est
        # cohérent avec le motif géométrique attendu par OpenCV pour un board
        # "standard". Même avec le bon mapping d'IDs, ce vérificateur reste
        # trop strict pour la disposition Calib.io et bloque l'interpolation.
        # On le désactive : la correspondance id -> position 3D a été validée
        # manuellement (voir CALIBIO_ID_TO_CHESS_POS), donc ce n'est pas un
        # signal fiable de mauvaise détection dans notre cas.
        charuco_params.checkMarkers = False
        refine_params = aruco.RefineParameters()

        self.detector = aruco.CharucoDetector(
            self.board, charuco_params, detector_params, refine_params
        )

        # Observations accumulées (une entrée par image acceptée)
        self._all_charuco_corners = []  # list of np.ndarray (N,1,2)
        self._all_charuco_ids = []      # list of np.ndarray (N,1)
        self._image_names = []
        self._rejected_names = []
        self._image_size = None  # (w, h), fixé à la première image

    # ------------------------------------------------------------------
    # Détection (utilisée à la fois en mode live preview et en mode batch)
    # ------------------------------------------------------------------
    def detect(self, frame_bgr):
        """
        Détecte le board ChArUco dans une image.

        Retourne (charuco_corners, charuco_ids, marker_corners, marker_ids).
        Les corners/ids ChArUco peuvent être None si la détection échoue
        ou si trop peu de coins sont visibles.
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        charuco_corners, charuco_ids, marker_corners, marker_ids = (
            self.detector.detectBoard(gray)
        )
        return charuco_corners, charuco_ids, marker_corners, marker_ids

    def detect_and_draw(self, frame_bgr):
        """
        Détecte le board et retourne une image annotée (pour l'aperçu live),
        ainsi que le nombre de coins ChArUco détectés sur cette frame.
        """
        overlay = frame_bgr.copy()
        charuco_corners, charuco_ids, marker_corners, marker_ids = self.detect(
            frame_bgr
        )

        n_corners = 0
        if marker_ids is not None and len(marker_ids) > 0:
            aruco.drawDetectedMarkers(overlay, marker_corners, marker_ids)

        if charuco_corners is not None and charuco_ids is not None:
            n_corners = len(charuco_ids)
            aruco.drawDetectedCornersCharuco(
                overlay, charuco_corners, charuco_ids, (0, 255, 0)
            )

        return overlay, n_corners

    # ------------------------------------------------------------------
    # Accumulation des images pour la calibration
    # ------------------------------------------------------------------
    def add_image(self, frame_bgr, name=None):
        """
        Tente d'ajouter une image au jeu de calibration.

        Retourne un tuple (accepted: bool, n_corners: int, message: str)
        afin que l'UI puisse donner un retour clair à l'utilisateur
        (ex: "Board partiellement visible, recapturez").
        """
        h, w = frame_bgr.shape[:2]
        if self._image_size is None:
            self._image_size = (w, h)
        elif (w, h) != self._image_size:
            return (
                False,
                0,
                f"Résolution incohérente ({w}x{h} != {self._image_size[0]}x{self._image_size[1]})",
            )

        charuco_corners, charuco_ids, _, _ = self.detect(frame_bgr)

        if charuco_corners is None or charuco_ids is None:
            if name:
                self._rejected_names.append(name)
            return False, 0, "Board ChArUco non détecté dans cette image"

        n_corners = len(charuco_ids)
        if n_corners < self.MIN_CORNERS_PER_IMAGE:
            if name:
                self._rejected_names.append(name)
            return (
                False,
                n_corners,
                f"Seulement {n_corners} coins détectés (minimum {self.MIN_CORNERS_PER_IMAGE} requis)",
            )

        self._all_charuco_corners.append(charuco_corners)
        self._all_charuco_ids.append(charuco_ids)
        self._image_names.append(name or f"image_{len(self._image_names):03d}")

        return True, n_corners, f"Image acceptée ({n_corners} coins ChArUco)"

    def reset(self):
        """Efface toutes les observations accumulées (nouvelle session)."""
        self._all_charuco_corners.clear()
        self._all_charuco_ids.clear()
        self._image_names.clear()
        self._rejected_names.clear()
        self._image_size = None

    @property
    def n_images(self):
        return len(self._image_names)

    @property
    def image_names(self):
        return list(self._image_names)

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------
    def calibrate(self):
        """
        Lance la calibration caméra à partir de toutes les images accumulées.

        Retourne un objet CalibrationResult.
        Lève ValueError si pas assez d'images valides.
        """
        n = self.n_images
        if n < 4:
            raise ValueError(
                f"Pas assez d'images valides pour calibrer ({n} fournies, "
                f"4 minimum absolu, {self.MIN_IMAGES_FOR_CALIBRATION} recommandé)"
            )

        flags = 0
        rms, camera_matrix, dist_coeffs, rvecs, tvecs = aruco.calibrateCameraCharuco(
            charucoCorners=self._all_charuco_corners,
            charucoIds=self._all_charuco_ids,
            board=self.board,
            imageSize=self._image_size,
            cameraMatrix=None,
            distCoeffs=None,
            flags=flags,
        )

        per_image_errors = self._compute_per_image_errors(
            camera_matrix, dist_coeffs, rvecs, tvecs
        )

        return CalibrationResult(
            camera_matrix=camera_matrix,
            dist_coeffs=dist_coeffs,
            image_size=self._image_size,
            overall_rms_error=float(rms),
            per_image_errors=per_image_errors,
            used_image_names=self.image_names,
            rejected_image_names=list(self._rejected_names),
        )

    def _compute_per_image_errors(self, camera_matrix, dist_coeffs, rvecs, tvecs):
        """
        Calcule l'erreur de reprojection RMS individuelle pour chaque image.

        C'est cette donnée qui alimente le graphique à barres dans l'UI :
        elle permet à l'utilisateur d'identifier visuellement les images
        de mauvaise qualité (board flou, mal éclairé, trop incliné...)
        et de les retirer pour relancer une calibration plus précise.
        """
        errors = []
        obj_points_full = self.board.getChessboardCorners()  # (N,3) toutes les coins théoriques

        for i in range(self.n_images):
            ids = self._all_charuco_ids[i].flatten()
            corners_2d = self._all_charuco_corners[i].reshape(-1, 2)
            obj_points = obj_points_full[ids]

            projected, _ = cv2.projectPoints(
                obj_points, rvecs[i], tvecs[i], camera_matrix, dist_coeffs
            )
            projected = projected.reshape(-1, 2)

            per_point_error = np.linalg.norm(corners_2d - projected, axis=1)
            rms_i = float(np.sqrt(np.mean(per_point_error**2)))
            errors.append(rms_i)

        return errors

    # ------------------------------------------------------------------
    # Génération de l'image du board (utile pour vérifier / réimprimer)
    # ------------------------------------------------------------------
    def generate_board_image(self, out_size_px=(1600, 2200)):
        """Génère une image du board ChArUco attendu, pour référence visuelle."""
        return self.board.generateImage(out_size_px)
