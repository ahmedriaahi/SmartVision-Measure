# SmartVision-Measure

Application desktop d'inspection dimensionnelle de pièces imprimées en 3D, basée sur la vision par ordinateur et l'IA.

Calibration caméra par mire ChArUco, segmentation YOLOv8-seg, mesure des dimensions en mm, comparaison avec le fichier STL de référence et génération d'un rapport PDF.

## Fonctionnalités

- **Calibration caméra** avec une mire ChArUco (8×11, case 20 mm, marqueur 15 mm), erreur RMS et graphique de reprojection
- **Mesure automatique de la distance** caméra–pièce via marqueurs ArUco et `solvePnP`
- **Segmentation** de la pièce avec YOLOv8-seg (flux caméra ou image statique)
- **Mesure** de la longueur, de la largeur et de l'aire (rectangle orienté minimal)
- **Comparaison avec un STL** : écart mesuré vs théorique, en mm et en %
- **Export** CSV / JSON et **rapport PDF** avec recommandations
- Thèmes sombre et clair

## Stack technique

PySide6 · OpenCV (contrib) · Ultralytics YOLOv8 · NumPy · numpy-stl · Matplotlib · ReportLab

## Démonstration 

https://github.com/user-attachments/assets/eb683a13-775e-466c-b755-d950b996d4a2

## Installation

Python 3.10 recommandé. Sur Ubuntu : `sudo apt install libxcb-cursor0`

```bash
python3.10 -m venv venv
source venv/bin/activate

# Étape 1 : dépendances
pip install -r requirements.txt

# Étape 2 : obligatoire (évite le conflit opencv-python / opencv-contrib-python)
pip install --force-reinstall --no-deps -r requirements_step2.txt
```

Vérification :

```bash
python -c "import cv2.aruco as a; print('aruco OK:', hasattr(a, 'calibrateCameraCharuco'))"
```

## Lancement

```bash
cd src
python main.py
```

## Utilisation

1. **Onglet Calibration** : capturer 8 à 15 images de la mire ChArUco *imprimée sur papier mat* (pas sur écran), puis lancer la calibration. RMS < 1 px recommandé.
2. **Onglet Modèle** : charger un modèle YOLOv8-seg (`.pt`), démarrer la caméra, activer la segmentation puis afficher les dimensions.
3. Optionnel : comparer avec un STL, exporter les mesures, générer le rapport PDF.

## Structure

```
src/
├── main.py                  # Point d'entrée
├── calibration_tab.py       # Onglet calibration
├── charuco_calibrator.py    # Logique de calibration ChArUco
├── reprojection_chart.py    # Graphique d'erreur de reprojection
├── aruco_distance.py        # Distance automatique via ArUco
├── model_tab.py             # Onglet segmentation et mesures
├── segmentation_engine.py   # YOLOv8-seg et calcul des dimensions
├── stl_compare.py           # Comparaison avec STL
├── report_generator.py      # Rapport PDF
└── theme_manager.py         # Thèmes
```

## Remarque

La précision de la segmentation dépend du modèle YOLOv8-seg utilisé. Pour de bons résultats, entraîner le modèle sur un dataset de pièces imprimées en 3D.

## Auteur

Ahmed Riahi
