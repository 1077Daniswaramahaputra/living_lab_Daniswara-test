from flask import Flask, request, jsonify, render_template, redirect, url_for, flash
import pandas as pd
import numpy as np
from scipy import stats
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import requests
import io
import os
import json

app = Flask(__name__)
app.secret_key = "living-lab-iot-placement"
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
ACTIVE_CSV = DATA_DIR / "active_data.csv"
SOURCE_FILE = DATA_DIR / "source.json"

# Revised proposal direction:
# Benefit: RSSI, Throughput
# Cost: Delay, Jitter, Packet Loss
CRITERIA = {
    "RSSI": "benefit",
    "Throughput": "benefit",
    "Delay": "cost",
    "Jitter": "cost",
    "Packet Loss": "cost",
    "LQI": "benefit",
}

ALIASES = {
    "Config": ["Config", "Configuration", "Konfigurasi", "Alternatif", "Scenario", "Skenario", "Placement"],
    "Node": ["Node", "Node ID", "Source", "Device", "Sensor Node"],
    "Link ID": ["Link ID", "Link", "LinkID"],
    "Timestamp": ["Timestamp", "Time", "Datetime", "Date", "Waktu"],
    "RSSI": ["RSSI", "Rssi", "RSSI (dBm)", "RSSI(dBm)"],
    "Throughput": ["Throughput", "throughput", "TP", "Throughput (kbps)", "throughput (kbps)"],
    "Delay": ["Delay", "Latency", "delay", "latency", "Latency (ms)", "Delay (ms)"],
    "Jitter": ["Jitter", "jitter", "Jitter (ms)"],
    "Packet Loss": ["Packet Loss", "Packet_Loss", "PacketLoss", "Loss", "PDR Loss", "Packet Loss (%)"],
    "LQI": ["LQI", "lqi"],
    "Temperature": ["Temperature", "Suhu", "temperature", "suhu"],
    "Humidity": ["Humidity", "Kelembaban", "humidity", "kelembaban", "RH", "Relative Humidity"],
    # PPM is retained as an environmental observation, not a TOPSIS criterion.
    # The exact gas/sensor is not yet identified, so no gas-specific interpretation is applied.
    "PPM": ["PPM", "ppm", "Air PPM", "Air_PPM", "Kualitas Udara PPM", "Kualitas_Udara_PPM", "Gas PPM", "Gas_PPM"],
    "R1": ["Repeater 1", "Repeater_1", "R1", "Repeater1"],
    "R2": ["Repeater 2", "Repeater_2", "R2", "Repeater2"],
}

def normalize_url(url):
    url = (url or "").strip()
    if "docs.google.com/spreadsheets" not in url:
        return url
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    try:
        sid = parts[parts.index("d") + 1]
    except Exception:
        return url
    gid = parse_qs(parsed.query).get("gid", ["0"])[0]
    return f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv&gid={gid}"

def save_source(kind, value):
    SOURCE_FILE.write_text(json.dumps({"kind": kind, "value": value}, ensure_ascii=False, indent=2), encoding="utf-8")

def get_source():
    if SOURCE_FILE.exists():
        try:
            return json.loads(SOURCE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"kind": "local", "value": str(ACTIVE_CSV)}

def read_csv_bytes(raw):
    return pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")

def standardize(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    rename = {}
    lower = {c.lower(): c for c in df.columns}
    for target, aliases in ALIASES.items():
        for a in aliases:
            if a.lower() in lower:
                rename[lower[a.lower()]] = target
                break
    df = df.rename(columns=rename)
    for c in CRITERIA:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["Temperature", "Humidity", "PPM"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def clean(df):
    if df.empty:
        return df.copy()
    out = df.copy().drop_duplicates()
    ranges = {
        "RSSI": (-150, 0),
        "Throughput": (0, np.inf),
        "Delay": (0, np.inf),
        "Jitter": (0, np.inf),
        "Packet Loss": (0, 100),
        "LQI": (0, 255),
        "Temperature": (-50, 100),
        "Humidity": (0, 100),
        # PPM must be non-negative. An upper bound is intentionally not imposed
        # until the gas sensor/model and its valid measurement range are confirmed.
        "PPM": (0, np.inf),
    }
    for c, (lo, hi) in ranges.items():
        if c in out.columns:
            out.loc[(out[c] < lo) | (out[c] > hi), c] = np.nan
    return out.reset_index(drop=True)

def environmental_analysis(df, group_col):
    """
    Descriptive supporting analysis only:
    - summarize environmental observations by configuration/group
    - calculate Spearman association between environmental variables and QoS
    Environmental variables are deliberately excluded from CRITERIA/TOPSIS.
    Correlation is descriptive and must not be interpreted as causation.
    """
    env_cols = [c for c in ["Temperature", "Humidity", "PPM"] if c in df.columns]
    qos_cols = [c for c in CRITERIA if c in df.columns]
    result = {
        "available": env_cols,
        "group_col": group_col,
        "summaries": [],
        "associations": [],
        "note": (
            "Analisis deskriptif pendukung; suhu, kelembaban, dan PPM tidak menjadi "
            "kriteria TOPSIS. Korelasi tidak membuktikan sebab-akibat. Arti PPM belum "
            "diinterpretasikan karena jenis gas/sensor belum dipastikan."
        ),
    }
    if not env_cols:
        return result

    if group_col and group_col in df.columns:
        numeric_cols = env_cols + [c for c in qos_cols if c not in env_cols]
        for group_name, group in df.groupby(group_col, dropna=True):
            row = {"group": str(group_name), "samples": int(len(group))}
            for col in numeric_cols:
                values = pd.to_numeric(group[col], errors="coerce").dropna() if col in group.columns else pd.Series(dtype=float)
                row[col] = round(float(values.mean()), 4) if len(values) else None
            result["summaries"].append(row)

    for env in env_cols:
        for qos in qos_cols:
            if env == qos:
                continue
            paired = df[[env, qos]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(paired) < 3 or paired[env].nunique() < 2 or paired[qos].nunique() < 2:
                rho, pvalue = None, None
            else:
                try:
                    corr = stats.spearmanr(paired[env], paired[qos], nan_policy="omit")
                    rho, pvalue = float(corr.statistic), float(corr.pvalue)
                except Exception:
                    rho, pvalue = None, None
            result["associations"].append({
                "environment": env,
                "qos": qos,
                "n": int(len(paired)),
                "spearman_rho": None if rho is None or not np.isfinite(rho) else round(rho, 4),
                "p_value": None if pvalue is None or not np.isfinite(pvalue) else round(pvalue, 6),
            })
    return result


def load_active():
    if not ACTIVE_CSV.exists():
        return pd.DataFrame()
    try:
        return standardize(pd.read_csv(ACTIVE_CSV))
    except Exception:
        return pd.DataFrame()

def find_group_column(df):
    # Research-safe: Config is preferred. Other columns are only fallback choices,
    # and the UI tells the user which grouping field is active.
    if "Config" in df.columns and df["Config"].nunique(dropna=True) >= 2:
        return "Config"
    if "Node" in df.columns and df["Node"].nunique(dropna=True) >= 2:
        return "Node"
    if "Link ID" in df.columns and df["Link ID"].nunique(dropna=True) >= 2:
        return "Link ID"
    return None

def phase1(df, group_col, metric):
    base = {
        "metric": metric, "normality_p": None, "homogeneity_p": None,
        "test": "-", "p_value": None, "selected": False, "status": "Tidak tersedia"
    }
    if not group_col or metric not in df.columns:
        return base
    groups = []
    for _, g in df.groupby(group_col):
        vals = pd.to_numeric(g[metric], errors="coerce").dropna().values
        if len(vals) >= 3:
            groups.append(vals)
    if len(groups) < 2:
        base["status"] = "Data kurang"
        return base

    normality = []
    for vals in groups:
        try:
            sample = vals if len(vals) <= 5000 else np.random.default_rng(7).choice(vals, 5000, replace=False)
            normality.append(float(stats.shapiro(sample).pvalue))
        except Exception:
            normality.append(np.nan)

    normal = bool(normality) and all(p >= 0.05 for p in normality if not np.isnan(p))
    try:
        lev_p = float(stats.levene(*groups, center="median").pvalue)
    except Exception:
        lev_p = np.nan

    if normal and not np.isnan(lev_p) and lev_p >= 0.05:
        test_name = "One-Way ANOVA"
        try:
            p = float(stats.f_oneway(*groups).pvalue)
        except Exception:
            p = np.nan
    else:
        test_name = "Kruskal-Wallis"
        try:
            p = float(stats.kruskal(*groups).pvalue)
        except Exception:
            p = np.nan

    base.update({
        "normality_p": float(min(normality)) if normality else None,
        "homogeneity_p": None if np.isnan(lev_p) else lev_p,
        "test": test_name,
        "p_value": None if np.isnan(p) else p,
        "selected": bool(not np.isnan(p) and p < 0.05),
        "status": "Dipilih" if (not np.isnan(p) and p < 0.05) else "Tidak dipilih",
    })
    return base

def entropy_weights(X):
    if X.shape[1] == 0:
        return np.array([])
    if X.shape[0] <= 1:
        return np.ones(X.shape[1]) / X.shape[1]
    colsum = X.sum(axis=0, keepdims=True)
    P = np.divide(X, colsum, out=np.zeros_like(X), where=colsum != 0)
    k = 1 / np.log(X.shape[0])
    e = []
    for j in range(X.shape[1]):
        pj = P[:, j]
        positive = pj > 0
        entropy_term = np.zeros_like(pj, dtype=float)
        entropy_term[positive] = pj[positive] * np.log(pj[positive])
        e.append(-k * entropy_term.sum())
    d = 1 - np.array(e)
    if np.isclose(d.sum(), 0):
        return np.ones(X.shape[1]) / X.shape[1]
    return d / d.sum()

def topsis(df, group_col, selected):
    if not group_col or not selected:
        return None
    grouped = df.groupby(group_col)[selected].mean(numeric_only=True).dropna()
    if len(grouped) < 2:
        return None

    X = grouped.values.astype(float)
    denom = np.sqrt((X ** 2).sum(axis=0))
    R = np.divide(X, denom, out=np.zeros_like(X), where=denom != 0)

    # Entropy uses normalized decision information.
    W = entropy_weights(R)
    V = R * W

    ideal_plus, ideal_minus = [], []
    for j, c in enumerate(selected):
        kind = CRITERIA.get(c, "cost")
        if kind == "benefit":
            ideal_plus.append(V[:, j].max())
            ideal_minus.append(V[:, j].min())
        else:
            ideal_plus.append(V[:, j].min())
            ideal_minus.append(V[:, j].max())

    ap = np.array(ideal_plus)
    am = np.array(ideal_minus)
    dplus = np.sqrt(((V - ap) ** 2).sum(axis=1))
    dminus = np.sqrt(((V - am) ** 2).sum(axis=1))
    ci = np.divide(dminus, dplus + dminus, out=np.zeros_like(dminus), where=(dplus + dminus) != 0)

    results = []
    for i, name in enumerate(grouped.index):
        score = float(ci[i])
        if score >= 0.80:
            status = "OPTIMAL"
        elif score >= 0.50:
            status = "KURANG OPTIMAL"
        else:
            status = "TIDAK OPTIMAL"
        results.append({
            "config": str(name),
            "score": round(score, 4),
            "dplus": round(float(dplus[i]), 4),
            "dminus": round(float(dminus[i]), 4),
            "status": status,
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i

    def records(mat):
        out = []
        for i, name in enumerate(grouped.index):
            row = {group_col: str(name)}
            for j, c in enumerate(selected):
                row[c] = round(float(mat[i, j]), 6)
            out.append(row)
        return out

    return {
        "results": results,
        "weights": {c: round(float(W[j]), 6) for j, c in enumerate(selected)},
        "decision": records(X),
        "normalized": records(R),
        "weighted": records(V),
        "group_col": group_col,
        "selected": selected,
    }

@app.route("/")
def index():
    df = clean(load_active())
    group_col = find_group_column(df)
    selected = [c for c in CRITERIA if c in df.columns]
    tests = [phase1(df, group_col, c) for c in selected]
    significant = [x["metric"] for x in tests if x["selected"]]
    # For dashboard demonstration, allow all available criteria only when no Phase-1
    # criterion is significant; actual research results should use the statistical filter.
    analysis = topsis(df, group_col, significant)
    return render_template(
        "index.html",
        rows=len(df),
        group_col=group_col,
        configs=[] if not group_col else [str(x) for x in df[group_col].dropna().unique()],
        tests=tests,
        significant=significant,
        analysis=analysis,
        source=get_source(),
    )

@app.route("/api/upload", methods=["POST"])
def upload():
    try:
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "File belum dipilih."}), 400
        raw = f.read()
        if f.filename.lower().endswith(".csv"):
            df = read_csv_bytes(raw)
        elif f.filename.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(raw))
        else:
            return jsonify({"error": "Gunakan CSV atau XLSX."}), 400
        df = standardize(df)
        df.to_csv(ACTIVE_CSV, index=False)
        save_source("upload", f.filename)
        return jsonify({"ok": True, "rows": len(df), "columns": list(df.columns)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/google-sheet", methods=["POST"])
def google_sheet():
    try:
        payload = request.get_json(silent=True) or request.form
        url = (payload.get("url") or "").strip()
        if not url:
            return jsonify({"error": "Link Google Sheet belum diisi."}), 400
        csv_url = normalize_url(url)
        r = requests.get(csv_url, timeout=25, headers={"User-Agent": "LivingLab-IoT-Dashboard/1.0"})
        r.raise_for_status()
        text = r.content.decode("utf-8-sig", errors="replace")
        if "<html" in text[:500].lower() or "<!doctype" in text[:500].lower():
            raise ValueError("Google Sheet tidak mengembalikan CSV. Periksa izin akses.")
        df = pd.read_csv(io.StringIO(text))
        df = standardize(df)
        df.to_csv(ACTIVE_CSV, index=False)
        save_source("google_sheet", csv_url)
        return jsonify({
            "ok": True,
            "rows": len(df),
            "columns": list(df.columns),
            "csv_url": csv_url,
        })
    except Exception as e:
        return jsonify({"error": f"Gagal mengambil Google Sheet: {e}"}), 400

@app.route("/api/data")
def api_data():
    df = clean(load_active())
    group_col = find_group_column(df)
    return jsonify({
        "rows": len(df),
        "columns": list(df.columns),
        "source": get_source(),
        "preview": df.tail(50).replace({np.nan: None}).to_dict(orient="records"),
        "environment": environmental_analysis(df, group_col),
    })

@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        df = clean(load_active())
        group_col = find_group_column(df)
        available = [c for c in CRITERIA if c in df.columns]
        tests = [phase1(df, group_col, c) for c in available]
        selected = [x["metric"] for x in tests if x["selected"]]

        # If the statistical filter does not select any criterion, do not silently
        # fabricate a TOPSIS ranking. Return a clear explanation for the UI instead.
        result = topsis(df, group_col, selected)
        message = None
        if not group_col:
            message = "Kolom alternatif tidak ditemukan. Tambahkan kolom Config atau gunakan Node/Link ID sebagai pengelompokan."
        elif len(df) == 0:
            message = "Dataset aktif kosong."
        elif not available:
            message = "Kolom QoS tidak dikenali. Periksa nama kolom RSSI, Throughput, Latency/Delay, Jitter, Packet Loss, dan LQI."
        elif not selected:
            message = "Tidak ada kriteria yang lolos Phase 1 (p-value < 0,05), sehingga TOPSIS tidak dihitung."
        elif result is None:
            message = "TOPSIS belum dapat dihitung. Pastikan ada minimal dua alternatif dengan nilai QoS numerik."
        return jsonify({
            "group_col": group_col,
            "tests": tests,
            "selected": selected,
            "topsis": result,
            "rows": len(df),
            "available": available,
            "message": message,
        })
    except Exception as e:
        app.logger.exception("Gagal menjalankan analisis TOPSIS")
        return jsonify({"error": f"Analisis gagal: {str(e)}"}), 500

@app.route("/analysis")
def analysis_page():
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
