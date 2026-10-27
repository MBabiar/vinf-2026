"""Regex extractors on short excerpts of real pages (markup copied from saved pages)."""

from animanga.parser import ann, mangaupdates
from animanga.parser.common import first_year, json_string, text

# ---------- shared helpers ----------


def test_text_keeps_words_together_and_drops_scripts() -> None:
    html = "<div><i>Cowboy Bebop</i>'s crew<br>Spike &amp; Jet<script>var x = 1;</script></div>"
    assert text(html) == "Cowboy Bebop's crew Spike & Jet"
    assert text("Average: <!-- -->8.6<!-- --> (<!-- -->3334<!-- --> votes)") == (
        "Average: 8.6 (3334 votes)"
    )


def test_first_year_and_json_string() -> None:
    assert first_year(["2000-10 (France)", "1998-04-03 to 1998-06-19 (first run)"]) == "1998"
    assert first_year(["unknown"]) == ""
    assert json_string("Female Fighter/s") == "Female Fighter/s"
    assert json_string("Protagonist\\\\u0027s Past") == "Protagonist's Past"


# ---------- Anime News Network ----------

ANN_PAGE = (
    '<div id="maincontent" class="maincontent encyc">'
    '<h1 id="page_header" class="same-width-as-main">\n  Cowboy Bebop (TV)\n</h1>'
    '<div id="infotype-19" class="encyc-info-type"><div class="fright">'
    '<table class="layout"><tr><td><img src="x.jpg"></td></tr></table></div>\n</div>'
    '<div id="infotype-related"><small>[ adapted from '
    '<a href="/encyclopedia/manga.php?id=99">Bebop (manga)</a>, serialized in '
    '<a href="/encyclopedia/manga.php?id=11709">[Jump Square]</a> ]<br><br></small>'
    "<b>Related anime:</b><br>"
    '    <a href="/encyclopedia/manga.php?id=1555">Cowboy Bebop (manga)</a> (spinoff)<br>'
    '    <a href="/encyclopedia/manga.php?id=26248">Cowboy Bebop (U.S. manga)</a><br>'
    '    <a href="/encyclopedia/anime.php?id=88">Cowboy Bebop 2 (TV)</a> (2000-03-04, sequel)'
    "<br><br></div>\n"
    '<div id="infotype-2" class="encyc-info-type">\n<strong>Alternative title:</strong>'
    '\t<div class="tab">カウボーイビバップ (Japanese)</div>'
    '\t<div class="tab">星際牛仔 (Chinese (Taiwan))</div>\n</div>\n'
    '<div id="infotype-31" class="encyc-info-type same-width-as-main">\n<strong>Themes:</strong>'
    '\t<span><a href="/genreresults?th=space" class="discreet">space</a></span>,'
    '\t<span><a href="/genreresults?th=politics" class="discreet">politics</a></span>,'
    '\t<span><a href="/genreresults?th=politics/x" class="discreet">politics</a></span>\n</div>\n'
    '<div id="infotype-36" class="encyc-info-type">'
    '<span><a href="/genreresults?th=space">find similar anime</a></span>\n</div>\n'
    '<div id="infotype-12" class="encyc-info-type br same-width-as-main">'
    "<strong>Plot Summary:</strong>"
    "\t<span>Spike Spiegel, a bounty hunter with a dark past.</span>\n</div>\n"
    '<div id="infotype-38" class="encyc-info-type br"><div class="fright">'
    "<strong>Watch <cite>Cowboy Bebop</cite> on:</strong>Crunchyroll</div></div>"
    '<div id="infotype-8" class="encyc-info-type br same-width-as-main">'
    "<strong>User Ratings:</strong>"
    "\t<span>12517 ratings have been given <style>.a { color: red; }</style>\n"
    "Seen in part or in whole by 21499 users, rank: #3 (of 10511)\n"
    "Weighted mean: 8.888 (Excellent), rank: #78 (of 10706)\n"
    "Bayesian estimate: 8.887 (Excellent), rank: #9 (of 8127)</span>\n</div>\n"
    '<div id="infotype-7" class="encyc-info-type">\n<strong>Vintage:</strong>'
    '\t<div class="tab">2000-10 (France)</div>'
    '\t<div class="tab">1998-04-03 to 1998-06-19 (first run, 12 eps)</div>\n</div>\n'
    '<div id="infotype-22" class="encyc-info-type same-width-as-main">\n<strong>Trivia:</strong> '
    '<a href="/encyclopedia/anime.php?id=13&amp;page=22">We have 189</a>\n</div>\n'
    '<div id="infotype-11" class="encyc-info-type br">\n<strong>Opening Theme:</strong>'
    '\t<div class="tab">"Tank!" by Seatbelts (eps 1-25)</div>\n</div>\n'
    '<div class="encyc-info-type br articles"><strong>Review:</strong><div class="limit-height">'
    '<div class="tab S0 show"><a href="/review/cowboy-bebop-box-set-dvd"><i>Cowboy Bebop</i> '
    "Box Set DVD</a> <small>(Feb 21, 2002)</small></div></div></div>"
    '<table class="encyc-interactive"><tr><td>releases</td></tr></table>'
    '<table id="credits"><tr><td><div class="overflow-down" data-encyc-credits="JP staff">'
    '<div class="ENTAB"><b>Series Director</b>: <a href="people.php?id=774">Shinichirō Watanabe'
    '</a><br></div><div class="ENTAB"><b title="Storyboard Artist">Storyboard</b>:<br>'
    '<a href="people.php?id=774">Shinichirō Watanabe</a> <small>(OP, ED; <span class="hover-box">'
    "<u>7 episodes</u><span><div>eps 1-2, 5, 9</div></span></span>)</small><br>"
    '<a class="discreet" href="people.php?id=4143">Tensai Okamura</a> <small>(ep 6)</small><br>'
    '</div><div class="ENTAB"><a class="ENCYC" href="reports.php?id=118#row1"><b>Music</b></a>: '
    "Maki Kitada (Bass)<br></div></div></td>"
    '<td colspan="2"><div data-encyc-credits="JP cast"><div class="ENTAB">'
    '<a href="people.php?id=792">Ai Uchikawa</a> <i>as</i> <br><nobr><b>Announcer</b></nobr> '
    "<small>(ep 4)</small><br><nobr><b>Announcer On Plane</b></nobr> <small>(ep 8)</small><br>"
    "</div></div></td>"
    '<td><div data-encyc-credits="JP company"><div class="ENTAB"><b>Animation Production</b>: '
    '<a href="company.php?id=34">Sunrise</a><br></div></div></td></tr></table>'
)


def test_ann_split_title() -> None:
    assert ann.split_title("Cowboy Bebop (TV)", "anime") == ("Cowboy Bebop", "TV")
    assert ann.split_title("Fruits Basket (TV 2)", "anime") == ("Fruits Basket", "TV")
    assert ann.split_title("Cutey Honey (TV 1/1973)", "anime") == ("Cutey Honey", "TV")
    assert ann.split_title("Claymore (manga, Yu Asagiri)", "manga") == ("Claymore", "manga")
    assert ann.split_title("[Jump Square]", "manga") == ("Jump Square", "magazine")
    assert ann.split_title("[Gundam]", "anime") == ("Gundam", "franchise")
    assert ann.split_title("Slayers - The Motion Picture", "anime") == (
        "Slayers - The Motion Picture",
        "movie",
    )


def test_ann_work_fields() -> None:
    out = ann.parse(ANN_PAGE, 13, "anime")
    work = out["works"][0]

    assert (work["title"], work["name"], work["type"]) == (
        "Cowboy Bebop",
        "Cowboy Bebop (TV)",
        "TV",
    )
    assert work["themes"] == "space; politics"  # duplicates on the page are dropped
    assert work["plot"] == "Spike Spiegel, a bounty hunter with a dark past."
    assert work["year"] == "1998"  # earliest vintage, not the first line
    assert (work["rating"], work["votes"], work["seen"]) == ("8.887", "12517", "21499")

    titles = {(t["title"], t["language"], t["main"]) for t in out["titles"]}
    assert titles == {
        ("Cowboy Bebop", "", 1),
        ("カウボーイビバップ", "Japanese", 0),
        ("星際牛仔", "Chinese (Taiwan)", 0),
    }

    fields = {(f["field"], f["value"]) for f in out["fields"]}
    assert ("Opening Theme", '"Tank!" by Seatbelts (eps 1-25)') in fields
    assert not any(f in ("Trivia", "Watch Cowboy Bebop on") for f, _ in fields)  # subpage, widget

    assert out["articles"] == [
        {
            "id": 13,
            "section": "Reviews",
            "level": "S0",
            "date": "2002-02-21",
            "url": "/review/cowboy-bebop-box-set-dvd",
            "title": "Cowboy Bebop Box Set DVD",
        }
    ]


def test_ann_relations_both_directions() -> None:
    edges = {
        (r["src"], r["relation"], r["dst"], r.get("note", ""))
        for r in ann.parse(ANN_PAGE, 13, "anime")["relations"]
    }
    assert edges == {
        (13, "adaptation", "99", ""),  # [ adapted from X ] on this page: this -> X
        (13, "serialized in", "11709", ""),
        ("1555", "spinoff", 13, ""),  # listed with (spinoff): the listed work -> this
        ("26248", "related", 13, ""),
        ("88", "sequel", 13, "2000-03-04"),
    }


def test_ann_credits() -> None:
    rows = ann.parse(ANN_PAGE, 13, "anime")["credits"]
    got = [
        (r["section"], r.get("role", ""), r.get("ref_id", ""), r["name"], r.get("character", ""))
        for r in rows
    ]
    assert got == [
        ("staff", "Series Director", "774", "Shinichirō Watanabe", ""),
        ("staff", "Storyboard", "774", "Shinichirō Watanabe", ""),
        ("staff", "Storyboard", "4143", "Tensai Okamura", ""),
        ("staff", "Music", "", "Maki Kitada", ""),
        ("cast", "", "792", "Ai Uchikawa", "Announcer"),
        ("cast", "", "792", "Ai Uchikawa", "Announcer On Plane"),
        ("company", "Animation Production", "34", "Sunrise", ""),
    ]
    assert [r.get("note", "") for r in rows] == [
        "",
        "OP, ED; eps 1-2, 5, 9",  # the full list from the hover box, not "7 episodes"
        "ep 6",
        "Bass",
        "ep 4",
        "ep 8",
        "",
    ]
    assert {r["language"] for r in rows} == {"JP"}


# ---------- MangaUpdates ----------


def _mu_field(key: str, label: str, value: str) -> str:
    return (
        f'<div class="info-box" data-cy="info-box-{key}-header"><b>{label}</b></div>'
        f'<div class="text" data-cy="info-box-{key}">{value}</div><br/>'
    )


MU_PAGE = (
    "<html><head><title>Claymore - MangaUpdates</title>"
    '<link rel="canonical" href="https://www.mangaupdates.com/series/xti92gy/claymore"/></head>'
    "<body>"
    # page data: the full category list (and a fake field that must not be read)
    '<script>self.__next_f.push([1,"{\\"categories\\":[{\\"series_id\\":1,'
    '\\"category\\":\\"Adapted to Anime\\",\\"votes\\":126,\\"votes_plus\\":130,'
    '\\"votes_minus\\":4,\\"added_by\\":5},{\\"series_id\\":1,\\"category\\":'
    '\\"Protagonist\\\\u0027s Past\\",\\"votes\\":2,\\"votes_plus\\":2,\\"votes_minus\\":0}]}'
    'data-cy=\\"info-box-type\\">Novel"])</script>'
    + _mu_field(
        "description",
        "Description",
        '<div class="x"><p>From Viz:<br/><!-- -->Monsters called Yoma prey on humans.</p></div>',
    )
    + _mu_field("type", "Type", "Manga")
    + _mu_field(
        "related_series",
        "Related Series",
        '<div><a title="Click for Series Info" href="https://www.mangaupdates.com/series/'
        'abc123/claymore-side"><span class="linked-name-module__9zptFq__name_underline">'
        "Claymore Side</span></a> <!-- -->(<!-- -->Side Story<!-- -->)</div>",
    )
    + _mu_field("associated", "Associated Names", "<div>Kureimoa</div><div>クレイモア</div>")
    + _mu_field(
        "anime",
        "Anime Start/End Chapter",
        "<div>Starts at <!-- -->Vol 1, Chap 1</div>"
        "<div>Ends at <!-- -->Vol 11, Chap 59 (Original Ending EP 24-26)</div>",
    )
    + _mu_field(
        "unknown",
        "User Rating",
        "<div>Average: <!-- -->8.6<!-- --> (<!-- -->3334<!-- --> <!-- -->votes)</div>"
        "<div>Bayesian Average: <b>8.58</b></div>",
    )
    + _mu_field(
        "genres",
        "Genre",
        '<span><a href="/series?genre=Action"><span><u>Action</u></span></a></span>'
        '<span>  <a href="/series?genre=Shounen"><span><u>Shounen</u></span></a></span><br/>'
        '<a rel="nofollow" href="/series?genre=Action_Shounen"><i><u>Search for series</u></i></a>',
    )
    + _mu_field(
        "authors",
        "Author(s)",
        '<div><a title="Click for Author Info" href="https://www.mangaupdates.com/author/'
        'muas9ak/yagi-norihiro"><span class="linked-name-module__9zptFq__name_underline">'
        "YAGI Norihiro</span></a></div>"
        '<div><span class="linked-name-module__9zptFq__name_underline">Qin Ye</span> '
        '[<a href="/cp/add-author?name=Qin+Ye"><u>Add</u></a>]</div>',
    )
    + _mu_field(
        "year", "Year", '<a href="https://www.mangaupdates.com/stats/new?year=2001">2001</a>'
    )
    + _mu_field(
        "publications",
        "Serialized In (magazine)",
        '<div><a href="/publishers/publication?name=Jump+SQ"><u>Jump SQ</u></a> '
        "(<!-- -->Chap 74 - 155<!-- -->)</div>",
    )
    + _mu_field(
        "english_publisher",
        "English Publisher",
        '<div><a title="Click for Publisher Info" href="https://www.mangaupdates.com/publisher/'
        '91qzdxd/viz"><span class="linked-name-module__9zptFq__name_underline">Viz</span></a> '
        "(<!-- -->27 Vols - Complete<!-- -->)</div>",
    )
    + _mu_field("unknown", "Recommendations", "N/A")
    + _mu_field(
        "unknown",
        "List Stats",
        '<div>On<!-- --> <a href="#"><u><b>7244</b></u></a> <!-- -->reading<!-- --> lists</div>',
    )
    + '<div class="row g-0" data-cy="comment-row"><a id="comment173999"></a>'
    '<div class="my-auto comment-row-module__Ro9Ypq__comment_title">Good read<!-- -->  </div>'
    'by<!-- --> <a href="#"><span class="linked-name-module__9zptFq__name_underline '
    'comment-row-module__Ro9Ypq__newsname">MoronicUser</span></a><br/>'
    '<time dateTime="2023-01-29T11:05:39.000Z">4 years ago</time>'
    '<span class="d-none">Rating:\xa0</span><em>N/A</em>'
    '<div class="p-3 col-12"><div class="mu-markdown-module___SC9hG__mu_markdown"><p>The first'
    " half was great.</p></div></div><em>Was this comment useful?</em></div>"
    "<footer>MangaUpdates</footer></body></html>"
)


def test_mu_series_fields() -> None:
    out = mangaupdates.parse(MU_PAGE, 1037)
    series = out["series"][0]

    assert (series["mu_id"], series["slug"], series["title"]) == ("xti92gy", "claymore", "Claymore")
    assert series["type"] == "Manga"  # not the "Novel" hidden in the script
    assert series["description"] == "From Viz: Monsters called Yoma prey on humans."
    assert series["genres"] == "Action; Shounen"
    assert series["year"] == "2001"
    assert (series["anime_start"], series["anime_end"], series["anime_end_vol"]) == (
        "1",
        "59",
        "11",
    )
    assert (series["rating"], series["votes"], series["reading"]) == ("8.58", "3334", "7244")

    assert [t["title"] for t in out["titles"]] == ["Claymore", "Kureimoa", "クレイモア"]
    assert out["related"] == [
        {
            "id": 1037,
            "relation": "Side Story",
            "other_mu_id": "abc123",
            "other_title": "Claymore Side",
        }
    ]


def test_mu_people_and_publishers() -> None:
    out = mangaupdates.parse(MU_PAGE, 1037)

    people = [(p["role"], p["author_id"], p["name"], p["note"]) for p in out["people"]]
    assert people == [("author", "muas9ak", "YAGI Norihiro", ""), ("author", "", "Qin Ye", "")]

    publishers = [
        (p["role"], p.get("publisher_id", ""), p["name"], p["note"]) for p in out["publishers"]
    ]
    assert publishers == [
        ("magazine", "", "Jump SQ", "Chap 74 - 155"),
        ("english", "91qzdxd", "Viz", "27 Vols - Complete"),
    ]


def test_mu_categories_from_page_data_and_comments() -> None:
    out = mangaupdates.parse(MU_PAGE, 1037)

    categories = [(c["category"], c["votes"], c["votes_minus"]) for c in out["categories"]]
    assert categories == [("Adapted to Anime", "126", "4"), ("Protagonist's Past", "2", "0")]

    assert out["comments"] == [
        {
            "id": 1037,
            "comment_id": "173999",
            "user": "MoronicUser",
            "date": "2023-01-29T11:05:39.000Z",
            "subject": "Good read",
            "text": "The first half was great.",
        }
    ]


def test_mu_anime_end_is_the_furthest_adaptation() -> None:
    value = (
        "<div>Starts at <!-- -->Vol 1, Chap 1 (2001/S1)  / Vol 6, Chap 36 (S2)</div>"
        "<div>Ends at <!-- -->Vol 7, Chap 38 (2001) / Vol 6, Chap 35 (S1) / Vol 23, Chap 136 (S3)"
        " S3 skips Chap 110</div>"
    )
    out = mangaupdates._anime(value)

    assert (out["anime_start"], out["anime_end"], out["anime_end_vol"]) == ("1", "136", "23")
    # a volume without its own chapter: the chapter of a later note does not count
    out = mangaupdates._anime(
        "<div>Ends at Vol 5 (2008 S2) Skips Vol 4, OVAs adapt Vol 7, Chap 2</div>"
    )
    assert (out["anime_end"], out["anime_end_vol"]) == ("", "5")
