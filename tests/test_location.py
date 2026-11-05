from app.extract.location import haversine_km, resolve_coordinates, split_place


class StubGeocoder:
    def __init__(self, mapping):
        self.mapping = mapping

    def lookup(self, query):
        return self.mapping.get(query)


def test_split_place():
    assert split_place("Qeshm, Kordestan, Iran") == ("Qeshm", "Iran")
    assert split_place("Iran") == (None, None)
    assert split_place("") == (None, None)


def test_haversine_reasonable():
    # Qeshm island vs the Kordestan mis-geocode
    assert 900 < haversine_km(26.95, 56.27, 35.44, 47.35) < 1300


def test_resolve_corrects_contradictory_place():
    geo = StubGeocoder({"Qeshm, Iran": (26.95, 56.27, "Iran")})
    lat, lon, changed = resolve_coordinates("Qeshm, Kordestan, Iran", 35.44, 47.35, geo)
    assert changed is True
    assert (lat, lon) == (26.95, 56.27)


def test_resolve_keeps_consistent_coords():
    geo = StubGeocoder({"Tehran, Iran": (35.689, 51.389, "Iran")})
    lat, lon, changed = resolve_coordinates("Tehran, Tehran, Iran", 35.689, 51.389, geo)
    assert changed is False
    assert (lat, lon) == (35.689, 51.389)


def test_resolve_rejects_result_outside_stated_country():
    # "Abyan, Iran" resolves to an Iranian village while GDELT meant Abyan, Yemen;
    # the country guard must refuse to move the marker on this ambiguity.
    geo = StubGeocoder({"Abyan, Iran": (36.91, 54.42, "Iran")})
    _lat, _lon, changed = resolve_coordinates("Abyan, Fars, Iran", 30.06, 51.53, geo)
    assert changed is True  # same country, so the move is allowed

    geo2 = StubGeocoder({"Abyan, Iran": (13.78, 46.14, "Yemen")})
    lat2, lon2, changed2 = resolve_coordinates("Abyan, Fars, Iran", 30.06, 51.53, geo2)
    assert changed2 is False
    assert (lat2, lon2) == (30.06, 51.53)


def test_resolve_without_city_is_noop():
    geo = StubGeocoder({})
    lat, lon, changed = resolve_coordinates("Iran", 32.0, 53.0, geo)
    assert changed is False
    assert (lat, lon) == (32.0, 53.0)


def test_resolve_handles_missing_coords():
    geo = StubGeocoder({"Qeshm, Iran": (26.95, 56.27, "Iran")})
    assert resolve_coordinates("Qeshm, Iran", None, None, geo) == (None, None, False)
