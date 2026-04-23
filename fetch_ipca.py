from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

CSV_URL = "https://www.tesourodireto.com.br/documents/d/guest/rendimento-investir-csv?download=true"
TZ = ZoneInfo("America/Sao_Paulo")

OUT_DIR = "site"
JSON_PATH = os.path.join(OUT_DIR, "ipca_hoje.json")
INDEX_PATH = os.path.join(OUT_DIR, "index.html")
HIST_PATH = os.path.join(OUT_DIR, "historico.csv")

LIMIARES = {
    "ipca_2032": 7.60,
    "ipca_2040": 7.30,
    "ipca_2045_js": 7.30,
}

ALVOS = {
    "Tesouro IPCA+ 2032": "ipca_2032",
    "Tesouro IPCA+ 2040": "ipca_2040",
    "Tesouro IPCA+ com Juros Semestrais 2045": "ipca_2045_js",
}

def extrair_taxa_percentual(texto: str) -> float:
    m = re.search(r"IPCA\s*\+\s*([0-9]+,[0-9]+)%", texto)
    if not m:
        raise ValueError(f"Não consegui extrair a taxa de: {texto}")
    return float(m.group(1).replace(",", "."))

def agora_sp() -> datetime:
    return datetime.now(TZ)

def hoje_sp_str() -> str:
    return agora_sp().strftime("%Y-%m-%d")

def agora_sp_iso() -> str:
    return agora_sp().isoformat()

def baixar_csv() -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/csv,text/plain,*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.tesourodireto.com.br/",
        "Origin": "https://www.tesourodireto.com.br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    session = requests.Session()
    r = session.get(CSV_URL, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text

def parsear_alvos(csv_texto: str) -> dict[str, float]:
    leitor = csv.DictReader(io.StringIO(csv_texto), delimiter=";")
    dados = {}

    for row in leitor:
        row = {str(k).lstrip("\ufeff").strip(): (v or "").strip() for k, v in row.items()}
        titulo = row.get("Título") or row.get("Titulo")
        rendimento = row.get("Rendimento anual do título") or row.get("Rendimento anual do titulo")

        if not titulo or not rendimento:
            continue

        titulo = titulo.replace("\r", "").replace("\n", "").strip()

        if titulo in ALVOS:
            dados[ALVOS[titulo]] = extrair_taxa_percentual(rendimento)

    faltando = [k for k in ALVOS.values() if k not in dados]
    if faltando:
        raise ValueError(f"Faltaram títulos no CSV: {faltando}")

    return dados

def ler_historico() -> list[dict]:
    if not os.path.exists(HIST_PATH):
        return []

    with open(HIST_PATH, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))

def salvar_historico(linhas: list[dict]) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(HIST_PATH, "w", encoding="utf-8", newline="") as f:
        campos = ["data", "ipca_2032", "ipca_2040", "ipca_2045_js"]
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for linha in linhas:
            w.writerow(linha)

def atualizar_historico(taxas: dict[str, float]) -> list[dict]:
    linhas = ler_historico()
    hoje = hoje_sp_str()

    nova = {
        "data": hoje,
        "ipca_2032": f"{taxas['ipca_2032']:.2f}",
        "ipca_2040": f"{taxas['ipca_2040']:.2f}",
        "ipca_2045_js": f"{taxas['ipca_2045_js']:.2f}",
    }

    linhas = [l for l in linhas if l["data"] != hoje]
    linhas.append(nova)
    linhas.sort(key=lambda x: x["data"])
    salvar_historico(linhas)
    return linhas

def forte_hoje(taxas: dict[str, float]) -> dict[str, bool]:
    return {k: taxas[k] >= LIMIARES[k] for k in LIMIARES}

def forte_ontem(historico: list[dict]) -> dict[str, bool]:
    if len(historico) < 2:
        return {k: False for k in LIMIARES}

    ontem = historico[-2]
    return {
        "ipca_2032": float(ontem["ipca_2032"]) >= LIMIARES["ipca_2032"],
        "ipca_2040": float(ontem["ipca_2040"]) >= LIMIARES["ipca_2040"],
        "ipca_2045_js": float(ontem["ipca_2045_js"]) >= LIMIARES["ipca_2045_js"],
    }

def montar_payload(taxas: dict[str, float], historico: list[dict]) -> dict:
    fh = forte_hoje(taxas)
    fo = forte_ontem(historico)

    alerta_precoce = any(fh.values())
    alerta_confirmado = any(fh[k] and fo[k] for k in fh)

    papeis = []
    if fh["ipca_2032"]:
        papeis.append("IPCA+ 2032")
    if fh["ipca_2040"]:
        papeis.append("IPCA+ 2040")
    if fh["ipca_2045_js"]:
        papeis.append("IPCA+ 2045 JS")

    if alerta_confirmado:
        mensagem = "ALERTA CONFIRMADO: zona forte em IPCA+"
    elif alerta_precoce:
        mensagem = "ALERTA PRECOCE: possível zona forte em IPCA+"
    else:
        mensagem = "Sem alerta hoje"

    return {
        "status": "ok",
        "data_referencia": hoje_sp_str(),
        "coletado_em": agora_sp_iso(),
        "origem": "Tesouro Direto - CSV oficial",
        "limiares": LIMIARES,
        "taxas": {
            "ipca_2032": round(taxas["ipca_2032"], 2),
            "ipca_2040": round(taxas["ipca_2040"], 2),
            "ipca_2045_js": round(taxas["ipca_2045_js"], 2),
        },
        "forte_hoje": fh,
        "forte_ontem": fo,
        "alerta_precoce": alerta_precoce,
        "alerta_confirmado": alerta_confirmado,
        "papeis_em_zona_forte": papeis,
        "mensagem": mensagem,
    }

def salvar_json(payload: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def salvar_index(payload: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Alerta IPCA</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Arial, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; }}
    pre {{ background: #f5f5f5; padding: 16px; border-radius: 8px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Alerta IPCA</h1>
  <p><strong>Status:</strong> {payload.get("status")}</p>
  <p><strong>Mensagem:</strong> {payload.get("mensagem")}</p>
  <p><strong>Coletado em:</strong> {payload.get("coletado_em")}</p>
  <p><a href="ipca_hoje.json">Abrir JSON</a></p>
  <pre>{json.dumps(payload, ensure_ascii=False, indent=2)}</pre>
</body>
</html>
"""
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)

def main() -> None:
    try:
        csv_texto = baixar_csv()
        taxas = parsear_alvos(csv_texto)
        historico = atualizar_historico(taxas)
        payload = montar_payload(taxas, historico)
    except Exception as e:
        payload = {
            "status": "erro",
            "data_referencia": hoje_sp_str(),
            "coletado_em": agora_sp_iso(),
            "mensagem": f"Falha na coleta: {str(e)}"
        }

    salvar_json(payload)
    salvar_index(payload)

if __name__ == "__main__":
    main()
