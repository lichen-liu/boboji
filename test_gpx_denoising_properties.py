"""Independent rule and metamorphic checks using invented trajectories/maps.

These cases compare physical observations, not logger IDs, XML ordering, or
the number of copies of an observation. No personal export is a fixture.
"""

from datetime import datetime, timedelta, timezone
from itertools import permutations, product

import pytest

import gpx_countries as script


A, B, C = ("Alpha", "AA"), ("Beta", "BB"), ("Gamma", "CC")
BASE = datetime(2030, 1, 1, tzinfo=timezone.utc)


def rectangle(label, west, east, south=-1, north=1):
    return {"type": "Feature", "properties": {"NAME_EN": label[0], "ISO_A2": label[1]},
            "geometry": {"type": "Polygon", "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]]]}}


def countries(named=True):
    features = [rectangle(A, -1, 0)]
    if named:
        features += [rectangle(B, 0, .02), rectangle(C, .02, 1)]
    return script.country_lookup({"type": "FeatureCollection", "features": features})


def observations(longitudes, minutes=None, latitude=0, sequence=1):
    minutes = range(len(longitudes)) if minutes is None else minutes
    return [(latitude, longitude, BASE + timedelta(minutes=minute), sequence)
            for longitude, minute in zip(longitudes, minutes)]


def denoise(records, lookup, **options):
    settings = {"coastal": False, "borders": False}
    settings.update(options)
    return script.denoise_samples(records, lookup, **settings)


def signature(fixes):
    return {(fix.latitude, fix.longitude, fix.time): fix.country for fix in fixes}


def gross_spike():
    # A normal short road trace with a 4,000+ km isolated position error.
    return [(0, 0, BASE, 1), (30, 30, BASE + timedelta(minutes=1), 1),
            (0, .001, BASE + timedelta(minutes=2), 1)]


def singleton_visit():
    # The middle coordinate is in B, within one km of A, with two distinct
    # confirming A epochs immediately before and after it.
    return observations([-.005, -.004, .005, -.004, -.005])


def test_motion_decisions_do_not_depend_on_segment_splitting_merging_or_renaming():
    records = gross_spike()
    expected = {(records[0][0], records[0][1], records[0][2]): A,
                (records[2][0], records[2][1], records[2][2]): A}
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        rectangle(A, -1, 1), rectangle(B, 29, 31, 29, 31)]})
    for identifiers in [(1, 1, 1), (1, 2, 1), (1, 2, 3), (78, 9, 78), (10, 11, 12)]:
        grouped = [(lat, lon, time, identifiers[i]) for i, (lat, lon, time, _) in enumerate(records)]
        fixes, report = denoise(grouped, lookup, visits=False)
        assert signature(fixes) == expected
        assert report["excluded"] == 1


def test_partial_exact_track_copies_do_not_become_competing_motion_evidence():
    lookup = lambda *_: A
    records = observations([i * .001 for i in range(13)])
    records[6] = (30, 30, records[6][2], 1)
    original, _ = denoise(records, lookup, visits=False)
    expected = signature(original)
    for indices in [range(13), range(3, 10), [6], range(6), range(7, 13)]:
        copied = records + [(lat, lon, time, 99) for i in indices
                            for lat, lon, time, _ in [records[i]]]
        fixes, report = denoise(copied, lookup, visits=False)
        assert signature(fixes) == expected
        assert sum(fix.count for fix in fixes) + report["excluded"] == len(copied)
        assert report["excluded"] == 1 + int(6 in indices)


@pytest.mark.parametrize("named", [True, False])
def test_singleton_named_country_and_unknown_use_the_same_context_rule(named):
    records = singleton_visit()
    fixes, report = denoise(records, countries(named), coastal=True)
    assert len(fixes) == len(records)
    assert all(fix.country == A for fix in fixes)
    assert report["visit_inferred"] == 1
    assert report["excluded"] == 0


def test_singleton_visit_is_invariant_to_input_order_and_segment_labels():
    records = singleton_visit()
    expected = {(lat, lon, time): A for lat, lon, time, _ in records}
    for order in permutations(records):
        for segmented in [False, True]:
            selected = [(lat, lon, time, index + 100 if segmented else 1)
                        for index, (lat, lon, time, _) in enumerate(order)]
            fixes, report = denoise(selected, countries())
            assert signature(fixes) == expected
            assert report["visit_inferred"] == 1


@pytest.mark.parametrize("copies", [1, 2, 100])
def test_same_epoch_copies_do_not_create_a_confirmed_foreign_visit(copies):
    records = singleton_visit()
    records += [(lat, lon, time, 100 + i) for i in range(copies - 1)
                for lat, lon, time, _ in [records[2]]]
    fixes, report = denoise(records, countries())
    assert all(fix.country == A for fix in fixes)
    assert report["visit_inferred"] == copies
    assert sum(fix.count for fix in fixes) == len(records)


def test_different_positions_in_the_same_foreign_epoch_still_form_one_epoch():
    records = singleton_visit()
    records.append((0, .008, records[2][2], 2))
    fixes, report = denoise(records, countries())
    assert all(fix.country == A for fix in fixes)
    assert report["visit_inferred"] == 2


@pytest.mark.parametrize("seconds", [.001, 1, 60, 300])
def test_a_coherent_multi_epoch_brief_visit_survives(seconds):
    records = observations([-.005, -.004, .005, .006, -.004, -.005])
    records[3] = (0, .006, records[2][2] + timedelta(seconds=seconds), 1)
    records[4] = (0, -.004, records[3][2] + timedelta(minutes=1), 1)
    records[5] = (0, -.005, records[3][2] + timedelta(minutes=2), 1)
    fixes, report = denoise(records, countries())
    assert [fix.country for fix in sorted(fixes, key=lambda item: item.time)] == [A, A, B, B, A, A]
    assert report["visit_inferred"] == report["excluded"] == 0


@pytest.mark.parametrize("weak", ["left", "right", "duplicates_left", "no_return", "entry", "old_anchor"])
def test_a_singleton_without_the_required_confirmation_is_not_suppressed(weak):
    records = singleton_visit()
    if weak == "left":
        records = records[1:]
    elif weak == "right":
        records = records[:-1]
    elif weak == "duplicates_left":
        records = [records[1]] * 30 + records[2:]
    elif weak == "no_return":
        records = records[:3]
    elif weak == "entry":
        records = records[2:]
    else:
        lat, lon, _, seq = records[0]
        records[0] = lat, lon, records[1][2] - timedelta(minutes=61), seq
    fixes, report = denoise(records, countries())
    assert any(fix.country == B for fix in fixes)
    assert report["visit_inferred"] == 0


@pytest.mark.parametrize("radius, expected", [(0, B), (500, B), (1000, A), (10000, A)])
def test_country_visit_uncertainty_uses_the_configured_polygon_distance(radius, expected):
    records = singleton_visit()
    fixes, _ = denoise(records, countries(), motion_slack_meters=radius)
    assert next(fix.country for fix in fixes if fix.time == records[2][2]) == expected


def test_a_single_foreign_epoch_outside_the_position_allowance_survives():
    records = singleton_visit()
    records[2] = 0, .12, records[2][2], 1  # More than 13 km from A, with feasible travel legs.
    fixes, report = denoise(records, countries())
    assert next(fix.country for fix in fixes if fix.time == records[2][2]) == C
    assert report["visit_inferred"] == report["excluded"] == 0


def test_a_conflicting_country_epoch_remains_ambiguous_regardless_of_input_order():
    records = singleton_visit()
    records.append((0, .025, records[2][2], 2))
    for selected in [records, list(reversed(records)), records[2:] + records[:2]]:
        fixes, report = denoise(selected, countries())
        at_epoch = {fix.country for fix in fixes if fix.time == records[2][2]}
        assert at_epoch == {B, C}
        assert report["visit_inferred"] == 0


def test_country_confirmation_does_not_use_physically_incompatible_anchors():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        rectangle(A, -1, 0, -80, 80), rectangle(B, 0, 1, -80, 80)]})
    records = singleton_visit()
    records[0] = -70, -.005, records[0][2], 1
    records[4] = 70, -.005, records[4][2], 1
    fixes, report = denoise(records, lookup)
    assert next(fix.country for fix in fixes if fix.time == records[2][2]) == B
    assert report["visit_inferred"] == 0


def test_inferred_country_labels_do_not_create_confirmation_for_another_singleton():
    records = observations([-.005, -.004, .005, -.004, .005, -.004, -.005])
    fixes, report = denoise(records, countries())
    assert sum(fix.country == B for fix in fixes) == 2
    assert report["visit_inferred"] == 0


def test_confirmation_context_can_span_an_hour_when_each_recording_gap_is_within_the_limit():
    records = observations([-.005, -.004, .005, -.004, -.005], minutes=[-90, -45, 0, 45, 90])
    fixes, report = denoise(records, countries(), max_gap_minutes=60)
    assert all(fix.country == A for fix in fixes)
    assert report["visit_inferred"] == 1


def test_two_alternating_coherent_recordings_do_not_delete_each_others_anchors():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        rectangle(A, -1, 1), rectangle(B, 29, 31, 29, 31)]})
    records = [(0 if i % 2 == 0 else 30, .001 * i if i % 2 == 0 else 30 + .001 * i,
                BASE + timedelta(minutes=i), 1 if i % 2 == 0 else 2) for i in range(8)]
    for ids in [None, list(range(8)), [1] * 8]:
        grouped = records if ids is None else [(lat, lon, time, ids[i])
                                             for i, (lat, lon, time, _) in enumerate(records)]
        fixes, report = denoise(grouped, lookup, visits=False)
        assert signature(fixes) == {(lat, lon, time): lookup(lat, lon) for lat, lon, time, _ in records}
        assert report["excluded"] == 0


def test_unrelated_later_map_coverage_cannot_enlarge_a_local_coastal_uncertainty_budget():
    lookup = countries(named=False)
    reference_data = {"type": "FeatureCollection", "features": [rectangle(A, -1, .09)]}
    reference_data["features"][0]["geometry"]["coordinates"] = [
        [[-1, -1], [.09, -1], [.09, 0], [.005, 0], [.005, 1], [-1, 1], [-1, -1]]]
    reference = script.country_lookup(reference_data)
    local = observations([-.01, .05, -.01], latitude=.1)
    later = [(lat, lon, time + timedelta(days=20), 10)
             for lat, lon, time, _ in observations([-.01, .08, -.01], latitude=-.1)]
    baseline, _ = denoise(local, lookup, coastal=True, visits=False,
                          motion_slack_meters=1000, coastal_reference=lambda _: reference)
    expanded, _ = denoise(local + later, lookup, coastal=True, visits=False,
                          motion_slack_meters=1000, coastal_reference=lambda _: reference)
    assert next(fix.country for fix in baseline if fix.time == local[1][2]) is None
    assert signature([fix for fix in expanded if fix.time <= local[-1][2]]) == signature(baseline)


def test_coordinate_only_map_evidence_agrees_for_trackpoints_pois_and_untimed_points():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        rectangle(A, -1, 0), rectangle(B, 0, 1)]})
    refs = {A: script.country_lookup({"type": "FeatureCollection", "features": [rectangle(A, -1, .015)]}),
            B: script.country_lookup({"type": "FeatureCollection", "features": [rectangle(B, .015, 1)]})}
    records = [(0, .005, BASE, 1), (0, .005, BASE, None),
               (0, .005, None, 2), (0, .005, None, None)]
    fixes, report = denoise(records, lookup, borders=True, visits=False, coastal_reference=refs.get)
    assert all(fix.country == A for fix in fixes)
    assert sum(fix.count for fix in fixes) == 4
    assert report["excluded"] == 0


def test_explanation_rows_are_deterministic_for_equal_time_rejections_with_different_counts():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        rectangle(A, -1, 1), rectangle(B, 29, 31, 29, 31)]})
    left = 0, 0, BASE, 1
    first = 30, 30, BASE + timedelta(minutes=1), 1
    second = 30.01, 30.01, BASE + timedelta(minutes=1), 2
    right = 0, .001, BASE + timedelta(minutes=2), 1
    explanations = set()
    for order in permutations([left, first, first, second, right]):
        _fixes, report = denoise(order, lookup, visits=False)
        explanations.add(script.format_decisions(report))
    assert len(explanations) == 1


def test_manual_coastal_radius_limits_unknown_visit_inference_as_well():
    records = singleton_visit()
    records[2] = 0, .018, records[2][2], 1  # About 2 km outside the country polygon.
    fixes, report = denoise(records, countries(named=False), coastal=True, gps_radius_meters=500)
    assert next(fix.country for fix in fixes if fix.time == records[2][2]) is None
    assert report["visit_inferred"] == 0


def test_coastal_opt_out_preserves_unknowns_even_when_visit_smoothing_is_enabled():
    records = singleton_visit()
    fixes, report = denoise(records, countries(named=False), coastal=False, visits=True)
    assert next(fix.country for fix in fixes if fix.time == records[2][2]) is None
    assert report["visit_inferred"] == 0


def test_visit_opt_out_preserves_an_unconfirmed_named_country_epoch():
    records = singleton_visit()
    fixes, report = denoise(records, countries(), visits=False)
    assert next(fix.country for fix in fixes if fix.time == records[2][2]) == B
    assert report["visit_inferred"] == 0


@pytest.mark.parametrize("third_reference", ["missing", "overlapping"])
def test_pointwise_map_adjudication_requires_one_unique_available_alternative(third_reference):
    lookup = countries()
    refs = {A: script.country_lookup({"type": "FeatureCollection", "features": [rectangle(A, -1, .015)]}),
            B: script.country_lookup({"type": "FeatureCollection", "features": [rectangle(B, .015, 1)]}),
            C: None if third_reference == "missing" else
            script.country_lookup({"type": "FeatureCollection", "features": [rectangle(C, -.01, 1)]})}
    records = [(0, .005, BASE, 1)]
    fixes, report = denoise(records, lookup, borders=True, visits=False, coastal_reference=refs.get)
    assert fixes[0].country == B
    assert report["border_corrected"] == 0


@pytest.mark.parametrize("enabled,borders,coastal,visits,manual", tuple(product([False, True], repeat=5)))
def test_control_matrix_respects_domain_opt_outs_and_manual_country_radius(enabled, borders, coastal, visits, manual):
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        rectangle(A, -1, 0), rectangle(B, .05, 1)]})
    a_data = {"type": "FeatureCollection", "features": [rectangle(A, -1, .06)]}
    a_data["features"][0]["geometry"]["coordinates"] = [
        [[-1, -1], [.06, -1], [.06, 0], [0, 0], [0, 1], [-1, 1], [-1, -1]]]
    b_data = {"type": "FeatureCollection", "features": [rectangle(B, .05, 1)]}
    b_data["features"][0]["geometry"]["coordinates"] = [
        [[.06, -1], [1, -1], [1, 1], [.05, 1], [.05, 0], [.06, 0], [.06, -1]]]
    references = {A: script.country_lookup(a_data), B: script.country_lookup(b_data)}
    records = []
    for block, (latitude, candidate) in enumerate([(.2, .055), (.2, .018), (-.2, .055)]):
        records.extend((lat, lon, time + timedelta(days=block * 2), seq + block)
                       for lat, lon, time, seq in observations([-.005, -.004, candidate, -.004, -.005],
                                                              latitude=latitude))
    poi_time = BASE + timedelta(days=4, hours=1)
    records.append((-.2, .055, poi_time, None))
    # Same evidence copied out of order, in another source segment.
    lat, lon, time, _ = records[2]
    records.append((lat, lon, time, 99))
    before = list(records)
    radius = 500 if manual else None
    fixes, report = script.denoise_samples(records, lookup, enabled=enabled, borders=borders,
                                         coastal=coastal, visits=visits, gps_radius_meters=radius,
                                         coastal_reference=references.get)
    assert records == before
    if not enabled:
        assert [(fix.latitude, fix.longitude, fix.time, fix.country) for fix in fixes] == [
            (lat, lon, time, lookup(lat, lon)) for lat, lon, time, _ in records]
        assert sum(fix.count for fix in fixes) == len(records)
        return
    assert sum(fix.count for fix in fixes) + report["excluded"] == len(records)
    assert report["excluded"] == 0  # Every recorded movement in this fixture is feasible.
    if not coastal:
        assert all(fix.country is None for fix in fixes if fix.raw_country is None)
    if not visits and not borders:
        assert all(fix.country == fix.raw_country for fix in fixes if fix.raw_country is not None)
    if manual:
        # The unknown northern point is ~2 km from A, beyond the 500m override,
        # and neither reference polygon claims it as its own coordinate.
        unknown_time = BASE + timedelta(days=2, minutes=2)
        assert next(fix.country for fix in fixes if fix.time == unknown_time) is None
        assert next(fix.country for fix in fixes if fix.time == BASE + timedelta(minutes=2)) == B
    assert next(fix.country for fix in fixes if fix.time == poi_time) == (A if borders else B)


def coastal_reference_support():
    lookup = script.country_lookup({"type": "FeatureCollection", "features": [
        rectangle(A, -1, 0), rectangle(B, .05, 1)]})
    references = {
        A: script.country_lookup({"type": "FeatureCollection", "features": [rectangle(A, -1, .03)]}),
        B: script.country_lookup({"type": "FeatureCollection", "features": [rectangle(B, .05, 1)]}),
    }
    return lookup, references.get


def test_reference_covered_unknowns_supply_geometry_evidence_before_visit_confirmation():
    lookup, reference = coastal_reference_support()
    records = observations([-.005, .018, -.005, .06, -.005, .018, -.005])
    fixes, report = denoise(records, lookup, borders=True, coastal=True, coastal_reference=reference)
    assert all(fix.country == A for fix in fixes)
    assert report["reference_confirmed"] == 2
    assert report["visit_inferred"] == 1
    foreign = next(fix for fix in fixes if fix.time == records[3][2])
    assert foreign.raw_country == B
    assert (foreign.reference_country or foreign.raw_country) == B


@pytest.mark.parametrize("coastal, expected", [(True, A), (False, None)])
def test_manual_context_radius_does_not_limit_direct_geometry_but_domain_opt_out_does(coastal, expected):
    lookup, reference = coastal_reference_support()
    # The coordinate is ~2km outside baseline A but directly covered by its
    # reference polygon. As an untimed POI it has no temporal confirmation.
    records = [(0, .018, None, None)]
    fixes, report = denoise(records, lookup, borders=True, coastal=coastal, gps_radius_meters=500,
                           coastal_reference=reference)
    assert fixes[0].country == expected
    assert fixes[0].raw_country is None
    assert report["reference_confirmed"] == int(coastal)
    assert report["visit_inferred"] == 0
