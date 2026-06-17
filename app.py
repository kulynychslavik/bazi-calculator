"""
BaZi (Four Pillars) перевірочний сайт.

Ввід: дата народження, час народження, місто/країна.
Вивід: 4 стовпи БаЦзи + денний майстер, у двох варіантах:
  1) "Простий"      — час як на годиннику, БЕЗ поправки довготи (як у ТЗ, крок 1).
  2) "LMT/довгота"  — з поправкою на справжній місцевий сонячний час.

Мета — звірити з bazi-calculator.com і зрозуміти, який варіант збігається.
Бібліотека розрахунку: lunar_python (Solar -> getLunar -> getEightChar).
"""

from datetime import datetime, timedelta

from flask import Flask, render_template, request
from lunar_python import Solar

# Геокодер і часовий пояс — опційні: якщо немає інтернету/мережа блокує,
# сайт усе одно покаже "простий" варіант.
try:
    import ssl
    import certifi
    from geopy.geocoders import Nominatim
    # macOS Python часто без системних сертифікатів — беремо certifi.
    _ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    _geocoder = Nominatim(user_agent="bazi-check-tool", ssl_context=_ssl_ctx)
except Exception:  # pragma: no cover
    _geocoder = None

try:
    from timezonefinder import TimezoneFinder
    _tf = TimezoneFinder()
except Exception:  # pragma: no cover
    _tf = None

import pytz

app = Flask(__name__)


def geocode_city(city: str):
    """Місто -> (lat, lng, display_name) або None."""
    if not _geocoder or not city:
        return None
    try:
        loc = _geocoder.geocode(city, language="uk", timeout=10)
        if loc:
            return loc.latitude, loc.longitude, loc.address
    except Exception:
        return None
    return None


def resolve_timezone(lat: float, lng: float, naive_dt: datetime):
    """Координати + дата -> (tz_name, utc_offset_h, dst_h, std_offset_h)."""
    if not _tf:
        return None
    tz_name = _tf.timezone_at(lat=lat, lng=lng)
    if not tz_name:
        return None
    tz = pytz.timezone(tz_name)
    aware = tz.localize(naive_dt)
    utc_offset = aware.utcoffset().total_seconds() / 3600.0
    dst = (aware.dst().total_seconds() / 3600.0) if aware.dst() else 0.0
    std_offset = utc_offset - dst  # стандартний пояс без літнього часу
    return tz_name, utc_offset, dst, std_offset


def eight_char(dt: datetime):
    """datetime -> dict з 4 стовпами + денний майстер."""
    solar = Solar.fromYmdHms(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    ec = solar.getLunar().getEightChar()
    return {
        "year": ec.getYear(),
        "month": ec.getMonth(),
        "day": ec.getDay(),
        "time": ec.getTime(),
        "day_master": ec.getDayGan(),  # небесний стовбур дня = денний майстер
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def lmt_correction_minutes(lng: float, std_offset_h: float) -> float:
    """
    Поправка на справжній місцевий сонячний час (LMT).
    Стандартний меридіан поясу = 15° * стандартний_зсув_годин.
    На кожен градус різниці довготи = 4 хвилини.
    """
    standard_meridian = 15.0 * std_offset_h
    return (lng - standard_meridian) * 4.0


@app.route("/", methods=["GET", "POST"])
def index():
    ctx = {"form": {}}

    if request.method == "POST":
        date_str = request.form.get("date", "").strip()
        time_str = request.form.get("time", "").strip()
        city = request.form.get("city", "").strip()
        ctx["form"] = {"date": date_str, "time": time_str, "city": city}

        # 1. Парсимо введені дату+час
        try:
            naive_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            ctx["error"] = "Невірний формат дати або часу."
            return render_template("index.html", **ctx)

        # 2. Простий варіант — час як на годиннику, без поправки
        ctx["simple"] = eight_char(naive_dt)

        # 3. Геокодинг + часовий пояс + LMT
        geo = geocode_city(city)
        if geo:
            lat, lng, address = geo
            ctx["geo"] = {"lat": round(lat, 4), "lng": round(lng, 4), "address": address}

            tzinfo = resolve_timezone(lat, lng, naive_dt)
            if tzinfo:
                tz_name, utc_offset, dst, std_offset = tzinfo
                corr_min = lmt_correction_minutes(lng, std_offset)
                # Справжній сонячний час: прибираємо DST + додаємо поправку довготи
                true_dt = naive_dt - timedelta(hours=dst) + timedelta(minutes=corr_min)

                ctx["tz"] = {
                    "name": tz_name,
                    "utc_offset": utc_offset,
                    "dst": dst,
                    "std_offset": std_offset,
                    "corr_min": round(corr_min, 1),
                }
                ctx["lmt"] = eight_char(true_dt)
            else:
                ctx["tz_error"] = "Не вдалося визначити часовий пояс за координатами."
        else:
            ctx["geo_error"] = (
                "Не вдалося отримати координати міста "
                "(немає інтернету або місто не знайдено). "
                "Показано лише простий варіант."
            )

    return render_template("index.html", **ctx)


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
