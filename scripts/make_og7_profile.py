"""Builds server/naviscoord/profiles/og7.json from default.json (Navis-mcp, projeto OG7/ARKT)."""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
src = root / "server" / "naviscoord" / "profiles" / "default.json"
dst = root / "server" / "naviscoord" / "profiles" / "og7.json"
p = json.loads(src.read_text(encoding="utf-8"))

p["name"] = "og7"
p["description"] = ("Perfil do projeto OG7 (ARKT): códigos de disciplina dos arquivos OG7 "
                    "(ARQ, EST, HID, ESG, ELE, INC, GAS, ARC) e categorias do Revit em português.")

d = p["disciplines"]
extra_patterns = {
    "ARQ": ["arquitetura"],
    "EST": ["estrutura", "fnd"],
    "HID": ["hidraulica", "agua"],
    "SAN": ["esg", "esgoto", "pluvial"],
    "RCI": ["inc", "incendio", "spk"],
    "ELE": ["eletrica"],
    "HVAC": ["arc", "climatizacao", "ar"],
}
# Categorias em português (Revit pt-BR) só onde a categoria é exclusiva de uma disciplina.
extra_categories = {
    "ARQ": ["Paredes", "Portas", "Janelas", "Pisos", "Forros", "Escadas", "Guarda-corpos", "Telhados",
            "Mobiliário", "Marcenaria", "Painéis de parede cortina", "Montantes de parede cortina",
            "Modelos genéricos", "Ambientes", "Rampas"],
    "EST": ["Vigas", "Pilares estruturais", "Fundações estruturais", "Fundação estrutural",
            "Estrutura estrutural", "Treliças estruturais", "Vergalhão estrutural", "Lajes"],
    "HVAC": ["Dutos", "Conexões de duto", "Acessórios de duto", "Terminais de ar", "Isolamentos de duto",
             "Equipamento mecânico", "Dutos flexíveis"],
    "ELE": ["Eletrodutos", "Conexões de eletroduto", "Bandejas de cabos", "Conexões da bandeja de cabos",
            "Luminárias", "Dispositivos elétricos", "Equipamentos elétricos", "Dispositivos de iluminação"],
    "RCI": ["Sprinklers"],
}
for code, pats in extra_patterns.items():
    rule = d[code]
    rule["file_patterns"] = list(dict.fromkeys(rule.get("file_patterns", []) + pats))
for code, cats in extra_categories.items():
    rule = d[code]
    rule["categories"] = list(dict.fromkeys(rule.get("categories", []) + cats))
# "ar" vira HVAC no OG7 (ARC = ar-condicionado); tira de ARQ para não empatar.
d["ARQ"]["file_patterns"] = [x for x in d["ARQ"]["file_patterns"] if x != "ar"]

# Gás: disciplina própria, só pelo nome do arquivo (tubos são ambíguos por categoria).
other = d.pop("OTRO", None)
d["GAS"] = {"label": "Gás", "categories": [], "file_patterns": ["gas", "glp"]}
if other is not None:
    d["OTRO"] = other

pairs = p["clash_matrix"]["pairs"]
pairs.extend([
    {"a": "EST", "b": "GAS", "type": "Hard", "tolerance_m": 0.001},
    {"a": "ARQ", "b": "GAS", "type": "Hard", "tolerance_m": 0.005},
    {"a": "GAS", "b": "ELE", "type": "Clearance", "tolerance_m": 0.05},
])

# Códigos do OG7 em tudo (chaves e valores): SAN->ESG, RCI->INC, HVAC->ARC.
RENAME = {"SAN": "ESG", "RCI": "INC", "HVAC": "ARC"}

def rename_key(k):
    if "|" in k:
        return "|".join(RENAME.get(part, part) for part in k.split("|"))
    return RENAME.get(k, k)

def rename(node):
    if isinstance(node, dict):
        return {rename_key(k): rename(v) for k, v in node.items()}
    if isinstance(node, list):
        return [rename(v) for v in node]
    if isinstance(node, str):
        return RENAME.get(node, node)
    return node

p = rename(p)
labels = {"ESG": "Esgoto", "INC": "Incêndio", "ARC": "Ar-condicionado", "ARQ": "Arquitetura",
          "EST": "Estrutura", "HID": "Hidráulica", "ELE": "Elétrica", "GAS": "Gás"}
for code, label in labels.items():
    p["disciplines"][code]["label"] = label

# Formato do complemento (Configurar): uma pasta por disciplina, escopo pelo código no nome do
# modelo (-ESG-), um conjunto com todos os elementos do Revit daquela disciplina.
p["_sets"] = ("Navis-mcp/OG7: um conjunto por disciplina com toda peça cujo arquivo de origem tem -CÓDIGO- "
              "(Item > Source File, ex.: OG7-ESG-EXE-004-5PV-R00.rvt). Funciona no NWD publicado, que abre "
              "como um modelo só, e num NWF com os NWC anexados. Nomes de propriedade como o Navisworks em "
              "inglês os exibe.")
p["sets"] = {"folders": [
    {"folder": code,
     "sets": [{"name": f"{code} - Elementos",
               "conditions": [{"tab": "Item", "property": "Source File", "test": "contains", "value": f"-{code}-"}]}]}
    for code in ("ARQ", "EST", "HID", "ESG", "ELE", "INC", "GAS", "ARC")
]}
p["clash"] = {
    "name_format": "{0} X {1}",
    "pairs": [{"a": x["a"], "b": x["b"], "test": x.get("type", "Hard"), "tolerance_m": x["tolerance_m"]}
              for x in p["clash_matrix"]["pairs"]],
}

dst.write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

sys.path.insert(0, str(root / "server"))
from naviscoord.profile import Profile  # noqa: E402

prof = Profile.load("og7")
problems = prof.validate()
print("problemas de validação:", problems or "nenhum")
for name in ["OG7-ESG-EXE-004-5PV-R00.nwc", "OG7-INC-EXE-002-TER-R00.nwc", "OG7-ARC-EXE-004-3PV-R00.nwc",
             "OG7-ARQ-EXE-004-5PV-R00.nwc", "OG7-EST-EXE-002-FND-R00.nwc", "OG7-GAS-EXE-002-TER-R00.nwc",
             "OG7-ELE-EXE-004-9PV-R00.nwc", "OG7-HID-EXE-003-1PV-R00.nwc"]:
    print(f"  {name:34s} -> {prof.discipline_for_filename(name)}")
print("pares de clash:", len(prof.clash_pairs()))
