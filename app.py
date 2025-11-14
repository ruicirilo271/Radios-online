# -*- coding: utf-8 -*-
import os
import uuid
import asyncio
import subprocess
import tempfile
from datetime import datetime, timedelta
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request, render_template, Response, stream_with_context
from shazamio import Shazam
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

USER_AGENT = "RuiRadioNeon/1.0"

# Cache de rádios (uuid -> info)
STATIONS = {}

# Histórico por rádio (últimas 50 músicas)
HISTORY = defaultdict(lambda: deque(maxlen=50))

# Cache de capas iTunes: (artist, song) -> url
COVER_CACHE = {}

# Cache Shazam: resultados recentes por estação
SHAZAM_LAST_RESULT = {}

# Cooldown Shazam (segundos)
SHAZAM_COOLDOWN = 60


# ─────────────────────────────────────────────────────────────
# RADIOBROWSER – BUSCA POR NOME
# ─────────────────────────────────────────────────────────────
def fetch_station_by_name(query: str):
    q = (query or "").strip().lower()
    if not q:
        return None

    # Alias local
    if "ballads" in q:
        info = {
            "id": "m80ballads_alias",
            "name": "M80 Ballads",
            "stream": "https://stream-icy.bauermedia.pt/m80ballads.aac",
            "country": "Portugal",
        }
        STATIONS[info["id"]] = info
        return info

    try:
        url = "https://de1.api.radio-browser.info/json/stations/search"
        payload = {"name": q, "limit": 10}
        r = requests.post(url, json=payload, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()

        data = r.json()
        if not data:
            return None

        st = data[0]
        info = {
            "id": st["stationuuid"],
            "name": st.get("name"),
            "stream": st.get("url_resolved") or st.get("url"),
            "country": st.get("country"),
        }

        STATIONS[info["id"]] = info
        return info
    except Exception as e:
        print("[ERRO fetch_station_by_name]", e)
        return None


# ─────────────────────────────────────────────────────────────
# RADIOBROWSER – BUSCA POR UUID
# ─────────────────────────────────────────────────────────────
def fetch_station_by_id(station_id: str):
    if not station_id:
        return None

    # alias
    if station_id == "m80ballads_alias":
        info = {
            "id": "m80ballads_alias",
            "name": "M80 Ballads",
            "stream": "https://stream-icy.bauermedia.pt/m80ballads.aac",
            "country": "Portugal",
        }
        STATIONS[info["id"]] = info
        return info

    if station_id in STATIONS:
        return STATIONS[station_id]

    try:
        url = f"https://de1.api.radio-browser.info/json/stations/byuuid/{station_id}"
        r = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()

        data = r.json()
        if not data:
            return None

        st = data[0]
        info = {
            "id": st["stationuuid"],
            "name": st.get("name"),
            "stream": st.get("url_resolved") or st.get("url"),
            "country": st.get("country"),
        }

        STATIONS[info["id"]] = info
        return info

    except Exception as e:
        print("[ERRO fetch_station_by_id]", e)
        return None


# ─────────────────────────────────────────────────────────────
# CAPAS ITUNES
# ─────────────────────────────────────────────────────────────
def get_itunes_cover(artist: str, song: str):
    if not artist or not song:
        return None

    key = (artist.lower(), song.lower())

    if key in COVER_CACHE:
        return COVER_CACHE[key]

    try:
        url = "https://itunes.apple.com/search"
        params = {"term": f"{artist} {song}", "entity": "song", "limit": 1}

        r = requests.get(url, params=params, timeout=6)
        r.raise_for_status()

        results = r.json().get("results", [])
        if not results:
            COVER_CACHE[key] = None
            return None

        art = results[0].get("artworkUrl100")
        if not art:
            COVER_CACHE[key] = None
            return None

        cover = art.replace("100x100bb", "600x600bb")
        COVER_CACHE[key] = cover
        return cover

    except Exception as e:
        print("[ERRO ITUNES]", e)
        COVER_CACHE[key] = None
        return None


# ─────────────────────────────────────────────────────────────
# NORMALIZAR ARTISTA / MÚSICA
# ─────────────────────────────────────────────────────────────
def normalize_artist_song(artist: str, song: str):
    if not artist or not song:
        return artist, song

    a = artist.strip()
    s = song.strip()

    # Se forem iguais, não mexe
    if a.lower() == s.lower():
        return a, s

    # Se a primeira é grande e a segunda pequena → inverter
    if len(a.split()) >= 3 and len(s.split()) <= 2 and len(a) > len(s) + 5:
        return s, a

    # "feat", "&", etc → segunda parte é artista → inverter
    if any(x in s.lower() for x in [" feat", " ft.", " with ", " & "]):
        return s, a

    return a, s


# ─────────────────────────────────────────────────────────────
# ICY METADATA
# ─────────────────────────────────────────────────────────────
def get_icy_metadata(stream_url: str):
    try:
        h = {"Icy-MetaData": "1", "User-Agent": USER_AGENT}
        r = requests.get(stream_url, headers=h, stream=True, timeout=8)
        r.raise_for_status()

        metaint = r.headers.get("icy-metaint") or r.headers.get("Icy-MetaInt")
        if not metaint:
            return None, None, None
        metaint = int(metaint)

        r.raw.read(metaint)
        size_byte = r.raw.read(1)
        if not size_byte:
            return None, None, None

        meta_len = size_byte[0] * 16
        if meta_len == 0:
            return None, None, None

        meta = r.raw.read(meta_len).rstrip(b"\0").decode("utf-8", errors="ignore")

        if meta.startswith("<?xml") or "<RadioInfo>" in meta:
            return "Desconhecido", "Desconhecido", meta

        title = meta
        if "StreamTitle='" in meta:
            title = meta.split("StreamTitle='")[1].split("';")[0]

        if " - " in title:
            a, s = title.split(" - ", 1)
            return normalize_artist_song(a.strip(), s.strip())[0], normalize_artist_song(a.strip(), s.strip())[1], meta

        return None, title.strip(), meta

    except Exception as e:
        print("[ERRO ICY]", e)
        return None, None, None


# ─────────────────────────────────────────────────────────────
# CAPTURA PARA SHAZAM
# ─────────────────────────────────────────────────────────────
def capturar_wav(stream_url: str, seconds=4):
    tmp = tempfile.gettempdir()
    out = os.path.join(tmp, f"{uuid.uuid4().hex}.wav")

    cmd = [
        "ffmpeg", "-y", "-loglevel", "quiet",
        "-user_agent", USER_AGENT,
        "-i", stream_url, "-t", str(seconds),
        "-ac", "1", "-ar", "44100",
        out,
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if os.path.exists(out) and os.path.getsize(out) > 2500:
            return out
    except Exception as e:
        print("[ERRO CAPTURA]", e)

    return None


async def identificar_shazam_async(path):
    try:
        shazam = Shazam()
        out = await shazam.recognize_song(path)
        track = out.get("track")
        if not track:
            return None, None
        return track.get("subtitle"), track.get("title")
    except:
        return None, None


def identificar_shazam(path):
    try:
        return asyncio.run(identificar_shazam_async(path))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(identificar_shazam_async(path))
        loop.close()
        return result


# ─────────────────────────────────────────────────────────────
# HISTÓRICO (sem duplicações, sem A-B / B-A)
# ─────────────────────────────────────────────────────────────
def add_to_history(station, artist, song):
    if not artist or not song:
        return
    if artist.lower() == "desconhecido" and song.lower() == "desconhecido":
        return

    hist = HISTORY[station]
    if hist:
        last = hist[0]
        la = last["artist"].lower()
        ls = last["song"].lower()

        # Igual
        if la == artist.lower() and ls == song.lower():
            return

        # Invertido
        if la == song.lower() and ls == artist.lower():
            return

    hist.appendleft({
        "artist": artist,
        "song": song,
        "time": datetime.now().strftime("%H:%M:%S")
    })


# ─────────────────────────────────────────────────────────────
# PROXY STREAM – NÃO DESLIGA
# ─────────────────────────────────────────────────────────────
@app.route("/proxy/<station_id>")
def proxy_stream(station_id):
    info = fetch_station_by_id(station_id)
    if not info:
        return "Rádio não encontrada", 404

    url = info.get("stream")
    if not url:
        return "Stream inválido", 404

    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print("❌ STREAM ERRO:", e)
        return "Erro no stream", 500

    def gerar():
        for chunk in r.iter_content(chunk_size=4096):
            if chunk:
                yield chunk

    mime = "audio/mpeg"
    if ".aac" in url:
        mime = "audio/aac"

    return Response(stream_with_context(gerar()), mimetype=mime)


# ─────────────────────────────────────────────────────────────
# ROTAS FLASK
# ─────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("search.html")


@app.route("/radio/<station_id>")
def radio_page(station_id):
    info = fetch_station_by_id(station_id)
    if not info:
        return "Rádio não encontrada", 404
    return render_template("index.html", radio_id=station_id, radio_name=info.get("name", "Rádio"))


# ─────────────────────────────────────────────────────────────
# API – SEARCH
# ─────────────────────────────────────────────────────────────
@app.route("/api/search_all")
def api_search_all():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "radios": []})

    try:
        url = "https://de1.api.radio-browser.info/json/stations/search"
        payload = {"name": q, "limit": 50}

        r = requests.post(url, json=payload, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()

        data = r.json()
        radios = [{
            "id": st["stationuuid"],
            "name": st.get("name"),
            "country": st.get("country"),
            "clickcount": st.get("clickcount", 0),
        } for st in data]

        return jsonify({"ok": True, "radios": radios})

    except Exception as e:
        print("[ERRO SEARCH]", e)
        return jsonify({"ok": False, "radios": []})


# ─────────────────────────────────────────────────────────────
# API – TOP 100 (corrigido)
# ─────────────────────────────────────────────────────────────
@app.route("/api/suggest/top100")
def api_suggest_top100():
    mirrors = [
        "https://api.radio-browser.info",
        "https://de1.api.radio-browser.info",
        "https://nl1.api.radio-browser.info",
        "https://at1.api.radio-browser.info",
        "https://uk1.api.radio-browser.info",
    ]

    for base in mirrors:
        try:
            url = f"{base}/json/stations/topvote/100"
            print("🔍 A tentar:", url)

            r = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": USER_AGENT}
            )
            r.raise_for_status()

            data = r.json()
            if not isinstance(data, list) or len(data) == 0:
                print("⚠️ Mirror vazio, a tentar o próximo...")
                continue

            radios = [{
                "id": st.get("stationuuid"),
                "name": st.get("name"),
                "country": st.get("country"),
                "clickcount": st.get("clickcount", 0),
            } for st in data]

            print("✅ Carregado Top100 com sucesso!")
            return jsonify({"ok": True, "radios": radios})

        except Exception as e:
            print(f"[ERRO MIRROR {base}]", e)

    print("❌ Falha total em todos os mirrors.")
    return jsonify({"ok": False, "radios": []})




# ─────────────────────────────────────────────────────────────
# API – GÉNERO
# ─────────────────────────────────────────────────────────────
@app.route("/api/suggest/genre")
def api_suggest_genre():
    genre = (request.args.get("g") or "").strip()
    if not genre:
        return jsonify({"ok": False, "radios": []})

    try:
        url = "https://de1.api.radio-browser.info/json/stations/search"
        payload = {"tag": genre, "limit": 50}

        r = requests.post(url, json=payload, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()

        data = r.json()
        radios = [{
            "id": st["stationuuid"],
            "name": st.get("name"),
            "country": st.get("country"),
            "clickcount": st.get("clickcount", 0),
        } for st in data]

        return jsonify({"ok": True, "radios": radios})

    except Exception as e:
        print("[ERRO GENRE]", e)
        return jsonify({"ok": False, "radios": []})


# ─────────────────────────────────────────────────────────────
# API – PAÍS (corrigido)
# ─────────────────────────────────────────────────────────────
@app.route("/api/suggest/country")
def api_suggest_country():
    country = (request.args.get("c") or "").strip()
    if not country:
        return jsonify({"ok": False, "radios": []})

    try:
        url = "https://de1.api.radio-browser.info/json/stations/search"
        payload = {"country": country, "limit": 50}

        r = requests.post(url, json=payload, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()

        data = r.json()
        radios = [{
            "id": st["stationuuid"],
            "name": st.get("name"),
            "country": st.get("country"),
            "clickcount": st.get("clickcount", 0),
        } for st in data]

        return jsonify({"ok": True, "radios": radios})

    except Exception as e:
        print("[ERRO COUNTRY]", e)
        return jsonify({"ok": False, "radios": []})


# ─────────────────────────────────────────────────────────────
# API – NOWPLAYING (ICY + Shazam + cooldown)
# ─────────────────────────────────────────────────────────────
@app.route("/api/nowplaying")
def api_nowplaying():
    station_id = request.args.get("station", "")

    info = fetch_station_by_id(station_id)
    if not info:
        return jsonify({"ok": False, "error": "Rádio inválida"})

    url = info.get("stream")
    if not url:
        return jsonify({"ok": False, "error": "Stream inválido"})

    # 1) Tenta ICY
    icy_artist, icy_song, raw = get_icy_metadata(url)
    print("🎙 ICY:", icy_artist, "-", icy_song)

    artist = icy_artist
    song = icy_song

    # 2) Se ICY falhar → Shazam com cooldown
    if (
        not artist or not song or
        artist.lower() == "desconhecido" or
        song.lower() == "desconhecido"
    ):
        now = datetime.now()
        last = SHAZAM_LAST_RESULT.get(station_id)

        if last and now - last["time"] < timedelta(seconds=SHAZAM_COOLDOWN):
            artist = last["artist"]
            song = last["song"]
            print("♻️ SHAZAM CACHE:", artist, "-", song)
        else:
            print("🎵 A usar Shazam…")
            path = capturar_wav(url, 4)
            if path:
                a2, s2 = identificar_shazam(path)
                os.remove(path)

                if a2 and s2:
                    artist, song = a2, s2
                    SHAZAM_LAST_RESULT[station_id] = {
                        "artist": artist,
                        "song": song,
                        "time": now
                    }

    artist = artist or "Desconhecido"
    song = song or "Desconhecido"

    add_to_history(station_id, artist, song)

    return jsonify({
        "ok": True,
        "artist": artist,
        "song": song,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


# ─────────────────────────────────────────────────────────────
# API – HISTÓRICO
# ─────────────────────────────────────────────────────────────
@app.route("/api/history")
def api_history():
    station_id = request.args.get("station", "")
    return jsonify({"ok": True, "tracks": list(HISTORY[station_id])})


# ─────────────────────────────────────────────────────────────
# API – CAPAS
# ─────────────────────────────────────────────────────────────
@app.route("/api/cover")
def api_cover():
    artist = request.args.get("artist", "").strip()
    song = request.args.get("song", "").strip()

    if artist.lower() == "desconhecido" or song.lower() == "desconhecido":
        return jsonify({"ok": True, "cover": "/static/default_cover.png"})

    cover = get_itunes_cover(artist, song)
    return jsonify({"ok": True, "cover": cover or "/static/default_cover.png"})


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)
