import requests
import re

API_URL = "https://graphql.anilist.co"


def clean_description(text: str, max_len: int = 300):
    if not text:
        return None
    text = re.sub(r"<.*?>", "", text)  # strip HTML
    return text[:max_len] + ("..." if len(text) > max_len else "")


def anilist_request(query, variables=None):
    r = requests.post(
        API_URL,
        json={"query": query, "variables": variables or {}}
    )
    data = r.json()

    if "errors" in data:
        print("AniList API error:", data["errors"])
        return None

    return data["data"]


def search_anime(search):
    query = """
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        id
        title { romaji }
        description(asHtml: false)
        coverImage { large medium color }
        genres
        episodes
        nextAiringEpisode {
          episode
          airingAt
        }
      }
    }
    """
    data = anilist_request(query, {"search": search})
    if not data:
        return None

    media = data["Media"]
    media["description"] = clean_description(media.get("description"))
    return media


def search_anime_by_id(anime_id):
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        title { romaji }
        description(asHtml: false)
        coverImage { large medium color }
        genres
        episodes
        nextAiringEpisode {
          episode
          airingAt
        }
      }
    }
    """
    data = anilist_request(query, {"id": anime_id})
    if not data:
        return None

    media = data["Media"]
    media["description"] = clean_description(media.get("description"))
    return media


def get_seasonal_anime(season: str, year: int, page: int = 1, per_page: int = 50):
    query = """
    query ($season: MediaSeason, $seasonYear: Int, $page: Int, $perPage: Int) {
      Page(page: $page, perPage: $perPage) {
        media(
          season: $season,
          seasonYear: $seasonYear,
          type: ANIME,
          sort: POPULARITY_DESC
        ) {
          id
          title { romaji }
          description(asHtml: false)
          genres
          episodes
          coverImage { medium }
        }
      }
    }
    """

    data = anilist_request(query, {
        "season": season.upper(),
        "seasonYear": year,
        "page": page,
        "perPage": per_page
    })

    if not data:
        return []

    media = data["Page"]["media"]
    for a in media:
        a["description"] = clean_description(a.get("description"), 250)

    return media
