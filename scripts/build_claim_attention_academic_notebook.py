from pathlib import Path
import textwrap
import nbformat as nbf

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "notebooks/validation_scoring/05_ml_anomaly_model_benchmark.ipynb"
OUT = ROOT / "notebooks/claim_attention/01_claim_attention_score_academic_end_to_end.ipynb"
def md(s): return nbf.v4.new_markdown_cell(textwrap.dedent(s).strip())
def code(s): return nbf.v4.new_code_cell(textwrap.dedent(s).strip())

nb = nbf.read(SRC, as_version=4)
cells = list(nb.cells)
cells[0] = md("""
# IRIS — Claim Attention Score de zéro à l'intégration ML et SHAP

Notebook académique end-to-end, explicable et reproductible.

Question de recherche : comment combiner des règles métier auditables et un signal
d'atypicité non supervisé, sans étiquettes de fraude confirmées, tout en préservant
traçabilité, robustesse et explicabilité locale ?

IRIS priorise des situations à examiner. Il ne prouve pas une fraude et la décision
finale reste humaine.
""")
cells[1:1] = [
md("""
## Résumé exécutif

Le score déterministe IRIS reste la référence métier explicable. Le ML ajoute un rang
d'atypicité pour révéler des profils non couverts par les règles. Le score métier n'est
jamais transformé en vérité terrain. SHAP explique le score brut du modèle, non une
probabilité de fraude. La contribution est un protocole reproductible de priorisation
sous absence de supervision fiable.
"""),
md("""
## Grain, anti-fuite et validité

- Grain : une ligne par dossier claim_sk.
- Les historiques utilisent seulement des événements strictement antérieurs.
- Aucun label humain stable : aucune accuracy, précision, recall, F1 ou ROC-AUC de
  fraude ne peut être revendiquée.
- Sont interdits comme features : score final, points ML, décision humaine, données
  postérieures à la décision et historique futur.
- Limites : migration 2019, jointures incomplètes, manquants non aléatoires, dérive,
  corrélations et absence de labels indépendants.

Le recouvrement ML/règles mesure une cohérence descriptive, jamais une précision.
"""),
md("""
## Protocole expérimental

Extraction versionnée en lecture seule, contrôle du grain, EDA, sélection raisonnée,
comparaison de six modèles, décision multi-critères, entraînement final, calibration
percentile, scénarios de charge de revue, SHAP global/local, artefacts et monitoring.
""")
]

cells += [
md("""
# Partie B — Sélection finale, SHAP et intégration

Le benchmark précédent constitue le noyau comparatif. Cette partie transforme la
recommandation en pipeline candidat intégrable, sans écriture PostgreSQL.
"""),
md("""
## Sélection raisonnée des variables

Sans cible validée, meilleure ne signifie pas prédictive de fraude. Une variable est
retenue si elle est disponible, non constante, suffisamment renseignée et non redondante
à |rho de Spearman| >= 0,95. Pour une paire redondante, la variable la moins manquante
est conservée ; l'ordre de la configuration départage les égalités.
"""),
code("""
selection_df = feature_eda[[
    "feature", "family", "missing_rate_before_imputation", "std"
]].copy()
selection_df["decision"] = "KEEP"
selection_df["reason"] = "Disponible, variable et non redondante"
selection_df.loc[selection_df["std"].fillna(0).le(0), ["decision", "reason"]] = [
    "DROP", "Variable constante"
]
selection_df.loc[
    selection_df["missing_rate_before_imputation"].ge(.80), ["decision", "reason"]
] = ["DROP", "Au moins 80% de valeurs manquantes"]

order = {name: pos for pos, name in enumerate(expected_features)}
corr_abs = X_ml.corr(method="spearman").abs()
upper = corr_abs.where(np.triu(np.ones(corr_abs.shape), k=1).astype(bool))
redundant_pairs = (
    upper.stack().rename("abs_spearman").reset_index()
    .rename(columns={"level_0": "feature_1", "level_1": "feature_2"})
    .query("abs_spearman >= 0.95").sort_values("abs_spearman", ascending=False)
)
for _, pair in redundant_pairs.iterrows():
    left, right = pair["feature_1"], pair["feature_2"]
    decisions = selection_df.set_index("feature")["decision"]
    if decisions[left] == "DROP" or decisions[right] == "DROP":
        continue
    missing = selection_df.set_index("feature")["missing_rate_before_imputation"]
    drop = right if (
        missing[left] < missing[right]
        or (missing[left] == missing[right] and order[left] < order[right])
    ) else left
    selection_df.loc[selection_df.feature.eq(drop), ["decision", "reason"]] = [
        "DROP", "Redondance forte; alternative mieux couverte ou priorisee"
    ]

selected_features = selection_df.loc[selection_df.decision.eq("KEEP"), "feature"].tolist()
X_final = X_ml[selected_features].copy()
display(redundant_pairs)
display(selection_df)
print(f"Variables retenues: {len(selected_features)}/{len(used_features)}")
assert len(selected_features) >= 5
assert np.isfinite(X_final.to_numpy(dtype=float)).all()
"""),
md("""
## Entraînement final et calibration

Isolation Forest est réentraîné sur le run complet avec 300 arbres. Un score ML de 0,95
signifie plus atypique que 95 % des dossiers du run, jamais 95 % de probabilité de fraude.
"""),
code("""
from datetime import datetime, timezone
import joblib
import shap

FINAL_MODEL_VERSION = "IRIS_CLAIM_ATTENTION_ACADEMIC_IF_V1_CANDIDATE"
SHAP_BACKGROUND_ROWS, SHAP_EXPLAIN_ROWS = 50, 40
FINAL_ARTIFACT_DIR = (
    BASE_DIR / "data/model_artifacts/claim_attention"
    / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
)
t0 = time.perf_counter()
final_model = IsolationForest(
    n_estimators=300, contamination="auto", max_samples="auto",
    random_state=RANDOM_STATE, n_jobs=-1
).fit(X_final)
raw_final = pd.Series(
    -final_model.score_samples(X_final), index=X_final.index, name="raw_anomaly_score"
)
score_final = pd.Series(
    percentile_scores(raw_final).to_numpy(), index=X_final.index, name="score_ml"
)
final_scores = enriched_df[["claim_sk", "claim_business_id"]].copy()
final_scores["raw_anomaly_score"] = raw_final
final_scores["score_ml"] = score_final
print(f"Run final: {len(final_scores):,} dossiers en {time.perf_counter()-t0:.2f}s")
display(final_scores[["raw_anomaly_score", "score_ml"]].describe(
    percentiles=[.50, .90, .95, .98, .99]
))
"""),
md("""
## Seuil selon la capacité de revue

Sans labels, optimiser F1 serait artificiel. Les scénarios top 1 %, 3 %, 5 % et 10 %
explicitent la charge. Le top 5 % est une proposition de démonstration à valider métier.
"""),
code("""
capacity_rates = [.01, .03, .05, .10]
capacity_table = pd.DataFrame({
    "review_rate": capacity_rates,
    "score_ml_threshold": [1-r for r in capacity_rates],
    "claims_to_review": [math.ceil(len(final_scores)*r) for r in capacity_rates],
})
SELECTED_REVIEW_RATE, SELECTED_THRESHOLD = .05, .95
final_scores["ml_review_candidate"] = final_scores.score_ml.ge(SELECTED_THRESHOLD)
display(capacity_table)
print("Volume candidat:", int(final_scores.ml_review_candidate.sum()))
"""),
md("""
## Explicabilité SHAP

SHAP décompose la sortie brute -score_samples. Une contribution positive augmente
l'atypicité par rapport à la référence. La calibration percentile reste séparée car
elle dépend de la population du run.
"""),
code("""
background = X_final.sample(
    n=min(SHAP_BACKGROUND_ROWS, len(X_final)), random_state=RANDOM_STATE
)
top_idx = score_final.nlargest(min(SHAP_EXPLAIN_ROWS//2, len(score_final))).index
regular = score_final[score_final.lt(.80)]
regular_idx = regular.sample(
    n=min(SHAP_EXPLAIN_ROWS-len(top_idx), len(regular)), random_state=RANDOM_STATE
).index
X_explain = X_final.loc[top_idx.union(regular_idx)]

def anomaly_output(values):
    frame = pd.DataFrame(values, columns=selected_features)
    return -final_model.score_samples(frame)

shap_explainer = shap.Explainer(
    anomaly_output, background, algorithm="permutation", feature_names=selected_features
)
shap_values = shap_explainer(X_explain, max_evals=2*len(selected_features)+1)
print("Observations expliquees:", len(X_explain))
"""),
code("""
shap.plots.bar(shap_values, max_display=min(15, len(selected_features)), show=False)
plt.title("Importance SHAP globale - score brut d'atypicite")
plt.tight_layout(); plt.show()
shap.plots.beeswarm(shap_values, max_display=min(15, len(selected_features)), show=False)
plt.title("Direction et amplitude des contributions SHAP")
plt.tight_layout(); plt.show()

global_shap = pd.DataFrame({
    "feature": selected_features,
    "mean_abs_shap": np.abs(shap_values.values).mean(axis=0),
}).sort_values("mean_abs_shap", ascending=False)
display(global_shap)

top_pos = int(np.argmax(score_final.loc[X_explain.index].to_numpy()))
display(final_scores.loc[X_explain.index[top_pos], [
    "claim_sk", "claim_business_id", "score_ml"
]].to_frame("value"))
shap.plots.waterfall(shap_values[top_pos], max_display=12, show=False)
plt.title("Explication locale d'un dossier tres atypique")
plt.tight_layout(); plt.show()
"""),
md("""
### Limites SHAP

SHAP explique le modèle, pas la cause du dossier. Une variable importante n'est pas
fraudogène. Les corrélations partagent les contributions et le résultat dépend de
l'arrière-plan. L'interface doit parler de situations à vérifier.
"""),
code("""
shap_frame = pd.DataFrame(
    shap_values.values, index=X_explain.index, columns=selected_features
)
rows = []
for idx in score_final.loc[X_explain.index].nlargest(min(20, len(X_explain))).index:
    contrib = shap_frame.loc[idx].sort_values(key=np.abs, ascending=False).head(3)
    row = final_scores.loc[idx, ["claim_sk", "claim_business_id", "score_ml"]].to_dict()
    for rank, (feature, value) in enumerate(contrib.items(), 1):
        row[f"reason_{rank}"] = (
            f"{feature}: valeur={X_final.loc[idx, feature]:.4g}, SHAP={value:+.4g}"
        )
    rows.append(row)
top_cases_for_review = pd.DataFrame(rows)
if not attention_df.empty:
    top_cases_for_review = top_cases_for_review.merge(
        attention_df[["claim_sk", "attention_score", "attention_level"]],
        on="claim_sk", how="left"
    )
top_cases_for_review
"""),
md("""
## Intégration et monitoring

L'inférence réutilise strictement l'ordre des features, médianes et quantiles appris.
Avant production : validation out-of-time, dérive des variables et du score, couverture
des jointures, taux d'imputation, volume au seuil, stabilité du top, revue des divergences
règles/ML et suivi SHAP.
"""),
code("""
model_card = {
    "model_version": FINAL_MODEL_VERSION,
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "feature_version": FEATURE_VERSION,
    "feature_run_id": feature_run_id,
    "features": selected_features,
    "calibration": "population_percentile",
    "review_threshold": SELECTED_THRESHOLD,
    "intended_use": "Priorisation humaine de dossiers a examiner",
    "prohibited_use": "Decision automatique ou preuve de fraude",
    "limitations": [
        "Absence de labels humains confirmes",
        "Percentile relatif au run",
        "Validation temporelle requise",
        "SHAP explique le modele, pas une causalite",
    ],
}
FINAL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
joblib.dump({
    "model": final_model,
    "features": selected_features,
    "imputation_values": imputation_values,
    "clip_quantiles": ml_config["preprocessing"]["clip_quantiles"],
    "model_card": model_card,
}, FINAL_ARTIFACT_DIR / "claim_attention_isolation_forest.joblib")
(FINAL_ARTIFACT_DIR / "model_card.json").write_text(
    json.dumps(model_card, ensure_ascii=False, indent=2), encoding="utf-8"
)
selection_df.to_csv(FINAL_ARTIFACT_DIR / "feature_selection.csv", index=False)
benchmark_df.to_csv(FINAL_ARTIFACT_DIR / "model_comparison.csv", index=False)
global_shap.to_csv(FINAL_ARTIFACT_DIR / "shap_global_importance.csv", index=False)
top_cases_for_review.to_csv(
    FINAL_ARTIFACT_DIR / "top_cases_for_human_review.csv", index=False
)
capacity_table.to_csv(FINAL_ARTIFACT_DIR / "review_capacity_scenarios.csv", index=False)
print("Artefacts:", FINAL_ARTIFACT_DIR)
"""),
md("""
## Validation académique et décision

GO technique candidat pour démonstration et revue humaine si les contrôles passent.
PARTIAL scientifique tant que labels indépendants et validation temporelle manquent.
"""),
code("""
checks = pd.DataFrame([
    ("grain_unique", features_df.claim_sk.is_unique),
    ("features_ge_5", len(selected_features) >= 5),
    ("matrice_finie", np.isfinite(X_final.to_numpy()).all()),
    ("modeles_ge_5", len(model_scores) >= 5),
    ("score_0_1", final_scores.score_ml.between(0, 1).all()),
    ("shap_fini", np.isfinite(shap_values.values).all()),
    ("limites_documentees", len(model_card["limitations"]) >= 3),
], columns=["check", "passed"])
display(checks)
assert checks.passed.all(), checks.loc[~checks.passed]
display(Markdown(f'''
### Conclusion du run

- Modele candidat principal : Isolation Forest.
- Variables retenues : {len(selected_features)}/{len(used_features)}.
- Population scoree : {len(final_scores):,} dossiers.
- Seuil candidat : top {SELECTED_REVIEW_RATE:.0%}, score_ml >= {SELECTED_THRESHOLD:.2f}.
- Interpretation : percentile d'atypicite, jamais probabilite de fraude.
- Decision : GO technique candidat / PARTIAL scientifique.
'''))
"""),
md("""
## Références essentielles

Liu, Ting et Zhou (2008), Isolation Forest, DOI 10.1109/ICDM.2008.17.
Breunig et al. (2000), LOF, DOI 10.1145/342009.335388.
Schölkopf et al. (2001), One-Class SVM, DOI 10.1162/089976601750264965.
Lundberg et Lee (2017), SHAP, arXiv 1705.07874.
Saito et Rehmsmeier (2015), Precision-Recall, DOI 10.1371/journal.pone.0118432.
""")
]

out = nbf.v4.new_notebook(
    cells=cells,
    metadata={**nb.metadata, "title": "IRIS Claim Attention Academic End-to-End ML SHAP"}
)
OUT.parent.mkdir(parents=True, exist_ok=True)
nbf.write(out, OUT)
print(f"Wrote {OUT} with {len(cells)} cells")


