"""Sentiment — URL routes (M07). Mounted under /api/v1/sentiment/."""
from django.urls import path

from .views import SentimentArticlesView, SentimentMarketView, SentimentSymbolView

urlpatterns = [
    path("market/", SentimentMarketView.as_view(), name="sentiment-market"),
    path("articles/", SentimentArticlesView.as_view(), name="sentiment-articles"),
    path("symbol/<str:sym>/", SentimentSymbolView.as_view(), name="sentiment-symbol"),
]
