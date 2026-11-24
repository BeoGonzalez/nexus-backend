from recommendations_service.application.services import RecommendationService


async def test_for_user_passes_user_and_limit_to_store(store):
    recs = await RecommendationService(store).get_for_user("alice", limit=2)
    assert [r.title for r in recs] == ["Hades II", "Celeste"]
    assert store.calls == [("user", "alice", 2)]


async def test_trending_respects_limit(store):
    assert [r.title for r in await RecommendationService(store).get_trending(limit=1)] == ["Elden Ring"]
