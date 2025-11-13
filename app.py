# -*- coding: utf-8 -*-
import os
import uuid
import asyncio
import subprocess
from datetime import datetime
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request, render_template

from shazamio import Shazam
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

USER_AGENT = "RuiRadioNeon/1.0"

# Cache de rádios
STATIONS = {}

# Histórico por rádio (evita duplicados)
HISTORY = defaultdict(lambda: deque(maxlen=40))


# ────────────────────────────── RADIOBROWSER ──────────────────────────────

def fetch_station_by_name(query: str):
    """Pesquisa no RadioBrowser de forma rápida (compatível com Vercel)."""

    q = query.strip().lower()

    # Alias interno
    if "ballads" in q:
        info = {
            "id": "m80ballads_alias",
            "name": "M80 Ballads",
            "stream": "https://stream-icy.bauermedia.pt/m80ballads.aac",
        }
        STATIONS[info["id"]] = info
        return info

    try:
        API = "https://de1.api.radio-browser.info/json/stations/search"
        payload = {"name": q, "limit": 10}

        r = requests.post(API, json=payload, timeout=6)
        if r.status_code != 200:
            return None

        data = r.json()
        if not data:
            return None

        st = data[0]

        info = {
            "id": st["stationuuid"],
            "name": st.get("name"),
            "stream": st.get("url_resolved") or st.get("url"),
        }

        STATIONS[info["id"]] = info
        return info

    except:
        return None


def fetch_station_by_id(station_id):
    if station_id in STATIONS:
        return STATIONS[station_id]

    try:
        API = f"https://de1.api.radio-browser.info/json/stations/byuuid/{station_id}"
        r = requests.get(API, timeout=6)
        r.raise_for_status()
        data = r.json()

        if not data:
            return None

        st = data[0]
        info = {
            "id": st["stationuuid"],
            "name": st.get("name"),
            "stream": st.get("url_resolved") or st.get("url"),
        }
        STATIONS[info["id"]] = info
        return info

    except:
        return None


# ───────────────────────────── CAPA (itunes) ─────────────────────────────

def get_itunes_cover(artist, song):
    if not artist or not song:
        return None

    try:
        url = "https://itunes.apple.com/search"
        params = {"term": f"{artist} {song}", "entity": "song", "limit": 1}

        r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()

        data = r.json().get("results", [])
        if not data:
            return None

        art = data[0].get("artworkUrl100")
        return art.replace("100x100bb", "600x600bb") if art else None

    except:
        return None


# ───────────────────────────── ICY METADATA ─────────────────────────────

def get_icy_metadata(stream_url):
    """Extrai artista/música de streams ICY rapidamente (compatível Vercel)."""

    try:
        headers = {
            "Icy-MetaData": "1",
            "User-Agent": USER_AGENT,
        }

        r = requests.get(stream_url, headers=headers, stream=True, timeout=6)
        r.raise_for_status()

        metaint = r.headers.get("icy-metaint") or r.headers.get("Icy-MetaInt")
        if not metaint:
            return None, None

        metaint = int(metaint)

        # Lê blocos até metadata
        r.raw.read(metaint)
        size = r.raw.read(1)
        if not size:
            return None, None

        meta_len = size[0] * 16
        if meta_len == 0:
            return None, None

        meta = r.raw.read(meta_len).decode("utf-8", errors="ignore")

        if "StreamTitle='" in meta:
            title = meta.split("StreamTitle='")[1].split("';")[0]
            if " - " in title:
                a, s = title.split(" - ", 1)
                return a.strip(), s.strip()

        return None, None

    except:
        return None, None


# ───────────────────────────── SHAZAM ─────────────────────────────

def capturar_wav(stream_url, seconds=4):
    """Captura áudio em /tmp para usar no ShazamIO (Vercel-safe)."""

    tmp = f"/tmp/{uuid.uuid4().hex}.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "quiet",
        "-i", stream_url,
        "-t", str(seconds),
        "-ac", "1",
        "-ar", "44100",
        tmp
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=7)
        if os.path.exists(tmp) and os.path.getsize(tmp) > 2500:
            return tmp
    except:
        pass

    return None


async def identificar_shazam(path):
    try:
        shazam = Shazam()
        out = await shazam.recognize_song(path)

        track = out.get("track")
        if not track:
            return None, None

        return track.get("subtitle"), track.get("title")
    except:
        return None, None


# ───────────────────────────── HISTÓRICO ─────────────────────────────

def add_to_history(station_id, a, s):
    if not a or not s:
        return
    if a.lower() == "desconhecido" and s.lower() == "desconhecido":
        return
    hist = HISTORY[station_id]
    if hist and hist[0]["artist"] == a and hist[0]["song"] == s:
        return
    hist.appendleft({
        "artist": a,
        "song": s,
        "time": datetime.now().strftime("%H:%M:%S")
    })


# ───────────────────────────── ROTAS ─────────────────────────────

@app.route("/")
def home():
    return render_template("search.html")


@app.route("/radio/<station_id>")
def radio_page(station_id):
    info = fetch_station_by_id(station_id)
    if not info:
        return "Rádio não encontrada", 404

    return render_template("index.html", radio_id=station_id, radio_name=info["name"])


@app.route("/api/search_all")
def api_search_all():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "radios": []})

    API = "https://de1.api.radio-browser.info/json/stations/search"
    payload = {"name": q, "limit": 50}

    try:
        r = requests.post(API, json=payload, timeout=8)
        data = r.json()

        results = [
            {
                "id": st["stationuuid"],
                "name": st["name"],
                "country": st.get("country")
            }
            for st in data
        ]

        return jsonify({"ok": True, "radios": results})

    except:
        return jsonify({"ok": False, "radios": []})


@app.route("/api/nowplaying")
def api_nowplaying():
    station_id = request.args.get("station")
    info = fetch_station_by_id(station_id)

    if not info:
        return jsonify({"ok": False, "error": "Rádio inválida"})

    stream = info.get("stream")
    artist, song = get_icy_metadata(stream)

    # FALLBACK SHAZAM
    if not artist or not song:
        path = capturar_wav(stream)
        if path:
            try:
                artist2, song2 = asyncio.run(identificar_shazam(path))
                if artist2 and song2:
                    artist, song = artist2, song2
            except:
                pass
            try:
                os.remove(path)
            except:
                pass

    artist = artist or "Desconhecido"
    song = song or "Desconhecido"

    add_to_history(station_id, artist, song)

    return jsonify({
        "ok": True,
        "artist": artist,
        "song": song,
        "time": datetime.now().strftime("%H:%M:%S")
    })


@app.route("/api/history")
def api_history():
    station = request.args.get("station")
    return jsonify({"ok": True, "tracks": list(HISTORY[station])})


@app.route("/api/cover")
def api_cover():
    a = request.args.get("artist", "")
    s = request.args.get("song", "")

    if a.lower() == "desconhecido" or s.lower() == "desconhecido":
        return jsonify({"ok": True, "cover": "/static/default_cover.png"})

    cover = get_itunes_cover(a, s)
    return jsonify({"ok": True, "cover": cover or "/static/default_cover.png"})

# ───────────────────────────── STREAM PROXY (necessário para tocar áudio) ─────────────────────────────

from flask import Response, stream_with_context

@app.route("/proxy/<station_id>")
def proxy_stream(station_id):
    """
    O proxy da Vercel NÃO pode manter conexão infinita.
    Mas para streams .mp3/.aac funciona em modo chunked.
    """
    info = fetch_station_by_id(station_id)
    if not info:
        return "Rádio não encontrada", 404

    stream_url = info.get("stream")
    if not stream_url:
        return "Stream inválido", 404

    headers = {
        "User-Agent": USER_AGENT,
        "Icy-Metadata": "0"
    }

    try:
        r = requests.get(stream_url, headers=headers, stream=True, timeout=8)
    except Exception as e:
        print("❌ ERRO AO LIGAR AO STREAM:", e)
        return "Erro ao ligar ao stream", 500

    def gerar():
        try:
            for chunk in r.iter_content(chunk_size=4096):
                if chunk:
                    yield chunk
        except GeneratorExit:
            pass
        except Exception as e:
            print("❌ ERRO NO STREAM:", e)

    # Mime-type automático
    mime = "audio/mpeg"
    if ".aac" in stream_url:
        mime = "audio/aac"
    if ".m3u8" in stream_url:
        mime = "application/vnd.apple.mpegurl"

    return Response(
        stream_with_context(gerar()),
        mimetype=mime,
        direct_passthrough=True
    )

# Vercel não usa app.run()
if __name__ == "__main__":
    app.run(debug=True)


