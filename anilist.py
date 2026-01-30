import requests

API_URL = "https://graphql.anilist.co"

def search_anime(search):
    query = """
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        id
        title {
          romaji
        }
        coverImage {
          large
          medium
          color
        }
        genres
        episodes
        nextAiringEpisode {
          episode
          airingAt
        }
      }
    }
    """
    variables = {"search": search}
    r = requests.post(API_URL, json={"query": query, "variables": variables})
    data = r.json()

    if "data" in data and data["data"]["Media"]:
        return data["data"]["Media"]
    return None


def search_anime_by_id(anime_id):
    query = """
    query ($id: Int) {
      Media(id: $id, type: ANIME) {
        id
        title {
          romaji
        }
        coverImage {
          large
          medium
          color
        }
        genres
        episodes
        nextAiringEpisode {
          episode
          airingAt
        }
      }
    }
    """
    variables = {"id": anime_id}
    r = requests.post(API_URL, json={"query": query, "variables": variables})
    data = r.json()

    if "data" in data and data["data"]["Media"]:
        return data["data"]["Media"]
    return None

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
          episodes
          coverImage { medium }
        }
      }
    }
    """

    variables = {
        "season": season.upper(),
        "seasonYear": year,
        "page": page,
        "perPage": per_page
    }

    data = anilist_request(query, variables)
    if not data:
        return []

    return data["Page"]["media"]
