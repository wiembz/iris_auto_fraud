# Integration des photos STAFIM dans la plateforme IRIS

## Objectif

Les colonnes `image1` a `image10` du fichier STAFIM contiennent des liens Google Drive. Certaines sources STAFIM peuvent pointer vers un PDF contenant les photos, et pas uniquement vers une image JPG/PNG. Ces liens ne garantissent pas l acces aux managers IRIS, car l affichage depend du compte Google autorise. La plateforme doit donc importer les photos dans un stockage controle par IRIS et servir ces images via l API.

## Architecture retenue

- Source brute : `staging.stg_inspection.image1..image10` conserve les URL Drive.
- Stockage fichiers : `data/inspection_images/<inspection_key>/...`.
- Metadonnees applicatives : `app.inspection_image_asset`.
- API : `/api/vhs/inspection-images/<asset_id>/content`.
- UX : galerie photos dans la fiche d inspection STAFIM.

## Statuts d import

| Statut | Signification |
|---|---|
| `IMPORTED` | Image copiee dans le stockage IRIS et servie par l API. |
| `NOT_IMPORTED` | URL source presente, mais image non importee, souvent a cause d un acces Drive restreint. |
| `ERROR` | Erreur technique d import. |
| `PENDING` | Image identifiee mais pas encore traitee. |

## Commandes d activation

```powershell
python backend/migrations/004_create_inspection_image_asset.py
python scripts/import_stafim_inspection_images.py --dry-run
python scripts/import_stafim_inspection_images.py --limit 20
python scripts/import_stafim_inspection_images.py
```

## Justification rapport PFE

Cette solution evite de dependre des droits Google Drive individuels et transforme les photos STAFIM en preuves documentaires accessibles depuis IRIS. La base conserve uniquement les metadonnees et la tracabilite source, tandis que les fichiers sont servis par une API controlee.

## Cas PDF

Certains liens Drive correspondent a un document PDF d inspection contenant plusieurs photos. IRIS detecte ce cas par signature binaire (`%PDF-`) et affiche une carte document ouvrable, au lieu de tenter de l afficher comme une image.

## Cas HEIC

Une partie des photos STAFIM peut provenir d iPhone et etre fournie au format HEIC. IRIS les conserve comme preuves documentaires (`image/heic`) et les presente comme fichiers photos ouvrables/telechargeables, car tous les navigateurs Windows ne savent pas les afficher en miniature.

## Previews JPEG pour HEIC

Pour offrir une experience homogene, IRIS genere une preview JPEG pour les photos HEIC. Le fichier HEIC original est conserve pour audit, tandis que l API sert la preview JPEG a l interface afin que les photos s affichent comme les autres images.

## Preview JPEG pour PDF

Pour les liens STAFIM qui pointent vers un PDF, IRIS conserve le PDF original, puis genere une preview JPEG depuis la premiere page. L interface affiche cette preview comme une photo normale ; le clic ouvre toujours le document original via l API.

Commandes :

```powershell
python backend/migrations/005_add_inspection_image_previews.py
python scripts/generate_pdf_inspection_previews.py --dry-run
python scripts/generate_pdf_inspection_previews.py
```

Ou pour generer toutes les previews HEIC et PDF :

```powershell
python scripts/generate_inspection_asset_previews.py --dry-run
python scripts/generate_inspection_asset_previews.py
```
