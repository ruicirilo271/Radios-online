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

# Histórico por rádio (últimas 50)
HISTORY = defaultdict(lambda: deque(maxlen=50))

# Cache de capas iTunes: (artist_lower, song_lower) -> url ou None
COVER_CACHE = {}

# Cache simples de Shazam: station_id -> {"artist": ..., "song": ..., "time": datetime}
SHAZAM_LAST_RESULT = {}

# Cooldown para chamadas ao Shazam por rádio (segundos)
SHAZAM_COOLDOWN = 60


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
            "country": "Portugal",
        }
        STATIONS[info["id"]] = info
        print("📻 Alias local usado (M80 Ballads)")
        return info

    try:
        url = "https://de1.api.radio-browser.info/json/stations/search"
        payload = {"name": q, "limit": 10}
        r = requests.post(url, json=payload, timeout=8, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        data = r.json()
        if not data:
            print("⚠️ RadioBrowser não devolveu resultados para:", q)
            return None

        st = data[0]
        info = {
            "id": st["stationuuid"],
            "name": st.get("name"),
            "stream": st.get("url_resolved") or st.get("url"),
            "country": st.get("country"),
        }
        STATIONS[info["id"]] = info
        print(f"✅ Rádio encontrada por nome: {info['name']} ({info['id']})")
        return info
    except Exception as e:
        print("[ERRO fetch_station_by_name]", e)
        return None


def fetch_station_by_id(station_id: str):
    """Obtém info da rádio via cache ou RadioBrowser."""
    if not station_id:
        return None

    # Alias local M80 Ballads
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
            print("⚠️ byuuid não devolveu dados para:", station_id)
            return None
        st = data[0]
        info = {
            "id": st["stationuuid"],
            "name": st.get("name"),
            "stream": st.get("url_resolved") or st.get("url"),
            "country": st.get("country"),
        }
        STATIONS[info["id"]] = info
        print(f"✅ Rádio carregada por UUID: {info['name']} ({info['id']})")
        return info
    except Exception as e:
        print("[ERRO fetch_station_by_id]", e)
        return None


# ───────────────────────────── CAPAS (iTunes) ─────────────────────────────

def get_itunes_cover(artist: str, song: str):
    if not artist or not song:
        return None

    a = artist.strip().lower()
    s = song.strip().lower()
    key = (a, s)

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
            print("⚠️ iTunes sem resultados para:", artist, "-", song)
            return None
        art = results[0].get("artworkUrl100")
        if not art:
            COVER_CACHE[key] = None
            return None
        big = art.replace("100x100bb", "600x600bb")
        COVER_CACHE[key] = big
        print("🖼  Capa iTunes:", big)
        return big
    except Exception as e:
        print("[ERRO ITUNES]", e)
        COVER_CACHE[key] = None
        return None


# ───────────────────────────── NORMALIZAÇÃO ARTISTA/MÚSICA ─────────────────────────────

def normalize_artist_song(artist: str, song: str):
    """Tenta garantir que devolvemos sempre (ARTISTA, MÚSICA)."""
    if not artist or not song:
        return artist, song

    a = artist.strip()
    s = song.strip()

    if a.lower() == s.lower():
        return a, s

    words_a = len(a.split())
    words_s = len(s.split())
    len_a = len(a)
    len_s = len(s)

    # Regra 1: parece (TÍTULO, ARTISTA) → trocar
    if (words_a >= 3 and words_s <= 2) and (len_a > len_s + 5):
        return s, a

    # Regra 2: se segunda parte tem feat/&/with → provavelmente é artista
    lower_s = s.lower()
    if any(x in lower_s for x in [" feat", " ft.", " feat.", " & ", " with "]):
        return s, a

    # Regra 3: primeira parte 1 palavra curta, segunda longa → manter
    if words_a == 1 and words_s >= 3:
        return a, s

    return a, s


# ───────────────────────────── ICY METADATA ─────────────────────────────

def get_icy_metadata(stream_url: str):
    """Lê metadata ICY. Se apanhar XML Bauer (RadioInfo) → devolve Desconhecido."""
    try:
        headers = {"Icy-MetaData": "1", "User-Agent": USER_AGENT}
        r = requests.get(stream_url, headers=headers, stream=True, timeout=8)
        r.raise_for_status()

        metaint_header = r.headers.get("icy-metaint") or r.headers.get("Icy-MetaInt")
        if not metaint_header:
            print("⚠️ Sem cabeçalho icy-metaint")
            return None, None, None

        try:
            metaint = int(metaint_header)
        except ValueError:
            print("⚠️ icy-metaint inválido:", metaint_header)
            return None, None, None

        r.raw.read(metaint)
        size_byte = r.raw.read(1)
        if not size_byte:
            return None, None, None

        meta_len = size_byte[0] * 16
        if meta_len == 0:
            return None, None, None

        meta_bytes = r.raw.read(meta_len)
        meta_str = meta_bytes.rstrip(b"\0").decode("utf-8", errors="ignore")

        if not meta_str.strip():
            return None, None, None

        # XML Bauer
        if meta_str.strip().startswith("<?xml") or "<RadioInfo>" in meta_str:
            print("📡 XML RadioInfo detectado (Bauer) → Desconhecido")
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
            first, second = title_part.split(" - ", 1)
            first = first.strip()
            second = second.strip()
            artist, song = normalize_artist_song(first, second)
        else:
            song = title_part.strip()
            if not song:
                return None, None, meta_str

        return artist, song, meta_str

    except Exception as e:
        print("[ERRO ICY]", e)
        return None, None, None


# ───────────────────────────── SHAZAM ─────────────────────────────

def capturar_wav(stream_url: str, seconds: int = 4):
    """Captura alguns segundos do stream para /tmp (compatível Vercel)."""
    tmpdir = tempfile.gettempdir()
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
            print("⚠️ Shazam sem 'track' no resultado")
            return None, None
        artist = track.get("subtitle")
        title = track.get("title")
        print("🎵 Shazam bruto:", artist, "-", title)
        return artist, title
    except Exception as e:
        print("[ERRO SHAZAM]", e)
        return None, None


def identificar_shazam(path: str):
    """Wrapper síncrono para usar o Shazam dentro da rota Flask."""
    try:
        return asyncio.run(identificar_shazam_async(path))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(identificar_shazam_async(path))
        finally:
            loop.close()


# ───────────────────────────── HISTÓRICO ─────────────────────────────

def add_to_history(station_id: str, artist: str, song: str):
    """Adiciona ao histórico com filtros anti-duplicados/invertidos."""
    if not artist or not song:
        return

    a = artist.strip()
    s = song.strip()

    if a.lower() == "desconhecido" and s.lower() == "desconhecido":
        return

    hist = HISTORY[station_id]
    if hist:
        last = hist[0]
        la = last["artist"].strip()
        ls = last["song"].strip()

        # Igual exatamente?
        if la.lower() == a.lower() and ls.lower() == s.lower():
            return

        # Igual mas trocado? (ex.: "A - B" e depois "B - A")
        if la.lower() == s.lower() and ls.lower() == a.lower():
            print("♻️ Ignorar swap duplicado no histórico:", a, "-", s)
            return

    hist.appendleft({
        "artist": a,
        "song": s,
        "time": datetime.now().strftime("%H:%M:%S")
    })
    print("📝 Histórico +1:", a, "-", s, "para", station_id)


# ───────────────────────────── PROXY STREAM ─────────────────────────────

@app.route("/proxy/<station_id>")
def proxy_stream(station_id):
    """Proxy do stream para evitar CORS no browser."""
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

    print("🔵 Proxy a enviar stream:", stream_url)
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
            "clickcount": st.get("clickcount", 0),
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
            "clickcount": st.get("clickcount", 0),
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
            "clickcount": st.get("clickcount", 0),
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
        # usar search por país para também ter clickcount
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
    print("🎙 ICY RAW:", raw)
    print("🎙 ICY PARSED:", icy_artist, "-", icy_song)

    artist = icy_artist
    song = icy_song

    # Shazam com cooldown
    if (
        not artist
        or not song
        or artist.lower() == "desconhecido"
        or song.lower() == "desconhecido"
    ):
        now = datetime.now()
        use_cached = False

        last = SHAZAM_LAST_RESULT.get(station_id)
        if last and now - last["time"] < timedelta(seconds=SHAZAM_COOLDOWN):
            artist = last["artist"]
            song = last["song"]
            use_cached = True
            print("♻️ Usar Shazam em cache:", artist, "-", song)

        if not use_cached:
            print("⚠️ Metadata fraca, a capturar áudio p/ Shazam…")
            path = capturar_wav(stream_url, seconds=4)
            if path:
                a2, s2 = identificar_shazam(path)
                try:
                    os.remove(path)
                except Exception:
                    pass
                if a2 and s2:
                    artist, song = a2, s2
                    print("🎵 SHAZAM FINAL:", artist, "-", song)
                    SHAZAM_LAST_RESULT[station_id] = {
                        "artist": artist,
                        "song": song,
                        "time": now,
                    }

    # Normalização final para garantir (ARTISTA, MÚSICA)
    artist, song = normalize_artist_song(artist or "Desconhecido", song or "Desconhecido")

    print("🎼 FINAL NOWPLAYING:", artist, "-", song)

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
