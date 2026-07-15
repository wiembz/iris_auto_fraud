from pathlib import Path
import nbformat
from nbclient import NotebookClient

p = Path("notebooks/claim_attention/01_claim_attention_score_academic_end_to_end.ipynb")
out = p.with_name(p.stem + "_executed.ipynb")
partial = p.with_name(p.stem + "_partial.ipynb")
nb = nbformat.read(p, as_version=4)

def started(cell, cell_index):
    preview = " ".join(cell.source.strip().split())[:100]
    print(f"START {cell_index:02d} {cell.cell_type}: {preview}", flush=True)

def completed(cell, cell_index):
    nbformat.write(nb, partial)
    print(f"DONE  {cell_index:02d}", flush=True)

client = NotebookClient(
    nb, timeout=1800, kernel_name="python3", allow_errors=False,
    resources={"metadata": {"path": str(p.parent.resolve())}},
    on_cell_start=started, on_cell_complete=completed,
)
client.execute()
nbformat.write(nb, out)
partial.unlink(missing_ok=True)
print(f"EXECUTED {out}", flush=True)
