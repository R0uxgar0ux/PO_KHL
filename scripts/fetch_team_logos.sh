#!/usr/bin/env sh
set -eu

TARGET_DIR="${1:-/app/static/team_logos}"
mkdir -p "$TARGET_DIR"

download() {
  name="$1"
  url="$2"
  out="$TARGET_DIR/$3"
  echo "[logos] downloading $name -> $out"
  curl -fsSL --retry 3 --connect-timeout 10 "$url" -o "$out"
}

download "Авангард" "https://content.sportslogos.net/logos/90/2709/full/8272_omsk_avangard-primary-2019.png" "avangard.png"
download "Металлург" "https://content.sportslogos.net/logos/90/2703/full/3128_magnitogorsk_metallurg-primary-2019.png" "metallurg.png"
download "Ак Барс" "https://content.sportslogos.net/logos/90/2715/full/4726_kazan_bars_ak-primary-2019.png" "ak_bars.png"
download "Трактор" "https://content.sportslogos.net/logos/90/2705/full/6251_chelyabinsk_traktor-alternate-2021.png" "traktor.png"
download "Сибирь" "https://content.sportslogos.net/logos/90/2712/full/3513_hc_sibir_novosibirsk-alternate-2015.png" "sibir.png"
download "Салават Юлаев" "https://content.sportslogos.net/logos/90/2697/full/7514_salavat__yulaev_ufa-primary-2016.png" "salavat_yulaev.png"
download "Автомобилист" "https://content.sportslogos.net/logos/90/2832/full/5709__avtomobilist_yekaterinburg-primary-2014.png" "avtomobilist.png"
download "Нефтехимик" "https://content.sportslogos.net/logos/90/2719/full/9214_neftekhimik_nizhnekamsk-primary-2018.png" "neftekhimik.png"
download "Северсталь" "https://content.sportslogos.net/logos/90/2701/full/7828_cherepovets_severstal-primary-2020.png" "severstal.png"
download "Динамо Мн" "https://content.sportslogos.net/logos/90/2698/full/9446_minsk_dinamo-primary-2020.png" "dynamo_minsk.png"
download "ЦСКА" "https://content.sportslogos.net/logos/90/2708/full/6830_cska_moscow-primary-2017.gif" "cska.gif"
download "Динамо М" "https://content.sportslogos.net/logos/90/2833/full/1217_moscow_dynamo-primary-2018.png" "dynamo_moscow.png"
download "Спартак" "https://content.sportslogos.net/logos/90/2699/full/9359_moscow_spartak-primary-2011.png" "spartak.png"
download "Торпедо" "https://content.sportslogos.net/logos/90/2717/full/9071_nizhny_novgorod_torpedo-primary-2019.png" "torpedo.png"
download "СКА" "https://content.sportslogos.net/logos/90/2707/full/2566_ska_saint_petersburg-primary-2015.png" "ska.png"
download "Локомотив" "https://content.sportslogos.net/logos/90/2710/full/44nc0zvkg10ltefgy9s2wg8r5.gif" "lokomotiv.gif"

echo "[logos] done"
