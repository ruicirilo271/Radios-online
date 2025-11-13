# -*- coding: utf-8 -*-
import os
import uuid
import asyncio
import subprocess
import tempfile
from datetime import datetime
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request, render_template, Response, stream_with_context
from shazamio import Shazam
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

USER_AGENT = "RuiRadioNeon/1.0"

# cache de rádios (uuid -> info)
STATIONS = {}

# histórico por rádio
HISTORY = defaultdict(lambda: deque(maxlen=50))


# ───────────────────────────── RADIOBROWSER ─────────────────────────────

def fetch_station_by_name(query: str):
    """Pesquisa rápida no RadioBrowser + alias local."""
    q = (query or "").strip().lower()
    if not q:
        return None

    # Alias M80 Ballads (exemplo local)
    if "ballads" in q:
        info = {
            "id": "m80ballads_alias",
            "name": "M80 Ballads",
            "stream": "https://stream-icy.bauermedia.pt/m80ballads.aac",
        }
        STATIONS[info["id"]] = info
        return info

    try:
        url = "https://de1.api.radio-browser.info/json/stations/search"
        payload = {"name": q, "limit": 10}
        r = requests.post(url, json=payload, timeout=8, headers={"User-Agent": USER_AGENT})
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


def fetch_station_by_id(station_id: str):
    """Obtém info da rádio via cache ou RadioBrowser."""
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
        r = requests.get(url, timeout=8, headers={"User-Agent": USER_AGENT})
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


# ───────────────────────────── CAPAS (iTunes) ─────────────────────────────

def get_itunes_cover(artist: str, song: str):
    if not artist or not song:
        return None
    try:
        url = "https://itunes.apple.com/search"
        params = {"term": f"{artist} {song}", "entity": "song", "limit": 1}
        r = requests.get(url, params=params, timeout=6)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return None
        art = results[0].get("artworkUrl100")
        if not art:
            return None
        return art.replace("100x100bb", "600x600bb")
    except Exception as e:
        print("[ERRO ITUNES]", e)
        return None


# ───────────────────────────── ICY METADATA ─────────────────────────────

def get_icy_metadata(stream_url: str):
    """
    Lê metadata ICY. Se apanhar XML Bauer (RadioInfo) → devolve Desconhecido.
    """
    try:
        headers = {"Icy-MetaData": "1", "User-Agent": USER_AGENT}
        r = requests.get(stream_url, headers=headers, stream=True, timeout=8)
        r.raise_for_status()

        metaint_header = r.headers.get("icy-metaint") or r.headers.get("Icy-MetaInt")
        if not metaint_header:
            return None, None, None

        try:
            metaint = int(metaint_header)
        except ValueError:
            return None, None, None

        # Saltar áudio
        r.raw.read(metaint)
        size_byte = r.raw.read(1)
        if not size_byte:
            return None, None, None

        meta_len = size_byte[0] * 16
        if meta_len == 0:
            return None, None, None

        meta_bytes = r.raw.read(meta_len)
        meta_str = meta_bytes.rstrip(b"\0").decode("utf-8", errors="ignore")

        # Se for XML RadioInfo (Bauer)
        if meta_str.strip().startswith("<?xml") or "<RadioInfo>" in meta_str:
            return "Desconhecido", "Desconhecido", meta_str

        title_part = meta_str
        if "StreamTitle='" in meta_str:
            try:
                title_part = meta_str.split("StreamTitle='", 1)[1].split("';", 1)[0]
            except Exception:
                pass

        artist = None
        song = None

        if " - " in title_part:
            artist, song = title_part.split(" - ", 1)
            artist = artist.strip()
            song = song.strip()
        else:
            song = title_part.strip() or None

        return artist, song, meta_str

    except Exception as e:
        print("[ERRO ICY]", e)
        return None, None, None


# ───────────────────────────── SHAZAM ─────────────────────────────

def capturar_wav(stream_url: str, seconds: int = 4):
    """
    Captura alguns segundos do stream para /tmp (compatível Vercel).
    """
    tmpdir = tempfile.gettempdir()  # /tmp na Vercel, pasta temp no Windows
    out_path = os.path.join(tmpdir, f"{uuid.uuid4().hex}.wav")

    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "quiet",
        "-user_agent", USER_AGENT,
        "-i", stream_url,
        "-t", str(seconds),
        "-ac", "1",
        "-ar", "44100",
        out_path,
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        if os.path.exists(out_path) and os.path.getsize(out_path) > 2500:
            print("✅ Captura OK:", out_path, "size:", os.path.getsize(out_path))
            return out_path
        print("⚠️ Ficheiro WAV inválido ou vazio")
    except Exception as e:
        print("[ERRO CAPTURA FFMPEG]", e)

    return None


async def identificar_shazam_async(path: str):
    try:
        shazam = Shazam()
        out = await shazam.recognize_song(path)
        track = out.get("track")
        if not track:
            return None, None
        return track.get("subtitle"), track.get("title")
    except Exception as e:
        print("[ERRO SHAZAM]", e)
        return None, None


def identificar_shazam(path: str):
    """
    Wrapper síncrono para usar o Shazam dentro da rota Flask.
    """
    try:
        return asyncio.run(identificar_shazam_async(path))
    except RuntimeError:
        # se já houver loop (mais raro na Vercel)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(identificar_shazam_async(path))
        finally:
            loop.close()


# ───────────────────────────── HISTÓRICO ─────────────────────────────

def add_to_history(station_id: str, artist: str, song: str):
    if not artist or not song:
        return
    a = artist.strip()
    s = song.strip()
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


# ───────────────────────────── PROXY STREAM ─────────────────────────────

@app.route("/proxy/<station_id>")
def proxy_stream(station_id):
    """
    Proxy do stream para evitar CORS no browser.
    """
    info = fetch_station_by_id(station_id)
    if not info:
        return "Rádio não encontrada", 404

    stream_url = info.get("stream")
    if not stream_url:
        return "Stream inválido", 404

    headers = {
        "User-Agent": USER_AGENT,
        "Icy-MetaData": "0",
    }

    try:
        r = requests.get(stream_url, headers=headers, stream=True, timeout=10)
        r.raise_for_status()
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

    mime = "audio/mpeg"
    if ".aac" in stream_url:
        mime = "audio/aac"
    if ".m3u8" in stream_url:
        mime = "application/vnd.apple.mpegurl"

    return Response(stream_with_context(gerar()), mimetype=mime, direct_passthrough=True)


# ───────────────────────────── ROTAS FLASK ─────────────────────────────

@app.route("/")
def home():
    return render_template("search.html")


@app.route("/radio/<station_id>")
def radio_page(station_id):
    info = fetch_station_by_id(station_id)
    if not info:
        return "Rádio não encontrada", 404
    return render_template("index.html", radio_id=station_id, radio_name=info.get("name", "Rádio"))


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
        } for st in data]

        return jsonify({"ok": True, "radios": radios})
    except Exception as e:
        print("[ERRO search_all]", e)
        return jsonify({"ok": False, "radios": []})


# ───────── SUGESTÕES: TOP100, GÉNERO, PAÍS ─────────

@app.route("/api/suggest/top100")
def api_suggest_top100():
    try:
        url = "https://de1.api.radio-browser.info/json/stations/topclick/100"
        r = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()
        radios = [{
            "id": st.get("stationuuid"),
            "name": st.get("name"),
            "country": st.get("country"),
        } for st in data]
        return jsonify({"ok": True, "radios": radios})
    except Exception as e:
        print("[ERRO TOP100]", e)
        return jsonify({"ok": False, "radios": []})


@app.route("/api/suggest/genre")
def api_suggest_genre():
    genre = (request.args.get("g") or "").strip().lower()
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
        } for st in data]
        return jsonify({"ok": True, "radios": radios})
    except Exception as e:
        print("[ERRO GENRE]", e)
        return jsonify({"ok": False, "radios": []})


@app.route("/api/suggest/country")
def api_suggest_country():
    country = (request.args.get("c") or "").strip()
    if not country:
        return jsonify({"ok": False, "radios": []})
    try:
        url = f"https://de1.api.radio-browser.info/json/stations/bycountry/{country}"
        r = requests.get(url, timeout=10, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()
        radios = [{
            "id": st["stationuuid"],
            "name": st.get("name"),
            "country": country,
        } for st in data[:50]]
        return jsonify({"ok": True, "radios": radios})
    except Exception as e:
        print("[ERRO COUNTRY]", e)
        return jsonify({"ok": False, "radios": []})


# ───────── NOWPLAYING + HISTÓRICO + CAPA ─────────

@app.route("/api/nowplaying")
def api_nowplaying():
    station_id = request.args.get("station", "")
    info = fetch_station_by_id(station_id)
    if not info:
        return jsonify({"ok": False, "error": "Rádio inválida"})

    stream_url = info.get("stream")
    if not stream_url:
        return jsonify({"ok": False, "error": "Stream inválido"})

    icy_artist, icy_song, raw = get_icy_metadata(stream_url)
    print("🎙 ICY:", icy_artist, "-", icy_song, "| raw:", raw)

    artist = icy_artist
    song = icy_song

    # Se ICY for insuficiente → tentar Shazam
    if not artist or not song or artist.lower() == "desconhecido" or song.lower() == "desconhecido":
        print("⚠️ Metadata fraca, tentar Shazam…")
        path = capturar_wav(stream_url, seconds=4)
        if path:
            a2, s2 = identificar_shazam(path)
            try:
                os.remove(path)
            except Exception:
                pass
            if a2 and s2:
                artist, song = a2, s2
                print("🎵 SHAZAM:", artist, "-", song)

    artist = artist or "Desconhecido"
    song = song or "Desconhecido"

    add_to_history(station_id, artist, song)

    return jsonify({
        "ok": True,
        "artist": artist,
        "song": song,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@app.route("/api/history")
def api_history():
    station_id = request.args.get("station", "")
    tracks = list(HISTORY[station_id])
    return jsonify({"ok": True, "tracks": tracks})


@app.route("/api/cover")
def api_cover():
    artist = (request.args.get("artist") or "").strip()
    song = (request.args.get("song") or "").strip()

    if artist.lower() == "desconhecido" or song.lower() == "desconhecido":
        return jsonify({"ok": True, "cover": "/static/default_cover.png"})

    cover = get_itunes_cover(artist, song)
    return jsonify({"ok": True, "cover": cover or "/static/default_cover.png"})


if __name__ == "__main__":
    app.run(debug=True)
