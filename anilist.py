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
