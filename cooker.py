import datetime
import dateutil.parser
from typing import Type, List

import feedparser
import regex
import requests
from jsonfeed import JSONFeed
from feedgenerator import Atom1Feed, SyndicationFeed

from util import logger


class Cooker(object):
    def __init__(
        self,
        name: str,
        repository_owner: str,
        repository: str,
        recipe: dict,
        limit: int,
    ):
        self.title = f"{name} by {repository}"
        self.description = recipe.get("description")
        if not self.description:
            self.description = "Auto generated by feedcooker with love."
        self.home_page_url = f"https://github.com/{repository}"
        self.feed_url = f"https://github.com/{repository}/well-done/{name}.json"
        self.author_name = repository_owner
        self.author_link = f"https://github.com/{repository_owner}"

        self.feeds_urls = recipe["urls"]
        self.limit = limit

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "feedcooker 0.1"})
        self._setup_filter(recipe.get("filter"))

    def _setup_filter(self, f: dict):
        if f is None:
            return
        if title := f.get("title"):
            self.title_filter = regex.compile(title)

    def cook(self) -> (JSONFeed, Atom1Feed):
        feed_items = []
        for url in self.feeds_urls:
            logger.debug(f"Fetching {url}")

            try:
                items = self._fetch_feed_items(url)

                if hasattr(self, "title_filter"):
                    items = [i for i in items if self.title_filter.search(i["title"])]

                feed_items.extend(items[: self.limit])
            except Exception as e:
                logger.error(f"Failed to fetch {url}: {e}")
                continue
            logger.info(f"Fetched {len(items)} entries from {url}")

        feed_items.sort(key=lambda x: x["pubdate"], reverse=True)

        logger.info(f"Final items {len(feed_items)}")

        return self._generate_feed(JSONFeed, feed_items), self._generate_feed(
            Atom1Feed, feed_items
        )

    def _fetch_url(self, url):
        # TODO: improve fetch with ETAG/LAST-MODIFIED
        resp = self.session.get(url)
        resp.raise_for_status()
        return resp

    # fetch feed from url
    def _fetch_feed_items(self, url) -> List[dict]:
        resp = self._fetch_url(url)

        content_type = resp.headers["Content-Type"]
        logger.debug(f"content type: {content_type}")

        if content_type.startswith("application/json"):
            feed = resp.json()
            return [self._json_feed_to_feed_item(feed, item) for item in feed["items"]]

        f = feedparser.parse(resp.text)
        if f is None or f["bozo"]:
            ex = f.get("bozo_exception") if f else "Unknown error"
            raise Exception(f"Failed to parse feed: {ex}")

        return [self._entry_to_feed_item(f, e) for e in f.entries]

    @staticmethod
    def _json_feed_to_feed_item(feed: dict, e: dict) -> dict:
        item = {
            "title": e["title"],
            "link": e["url"],
            "unique_id": e["id"],
        }

        summary = e.get("summary")
        content = e.get("content_html") if e.get("content_html") else e.get("content")

        if content:
            # prefer use content as description
            item["description"] = content
            item["content"] = content
        elif summary:
            item["description"] = summary
        else:
            item["description"] = ""

        author_detail = e.get("author") if e.get("author") else feed.get("author")
        if author_detail:
            item["author_name"] = author_detail.get("name")
            item["author_link"] = author_detail.get("url")

        pubdate = (
            e.get("date_published")
            if e.get("date_published")
            else e.get("date_modified")
        )
        if pubdate:
            item["pubdate"] = dateutil.parser.parse(pubdate)
        else:
            item["pubdate"] = datetime.datetime.now()

        update = e.get("date_modified")
        if update:
            item["update"] = dateutil.parser.parse(update)

        logger.debug(f"item: {item}")
        return item

    # mapping rss/atom entry to JSONFeed item(using in JSONFeed.add_item)
    @staticmethod
    def _entry_to_feed_item(feed, e) -> dict:
        item = {
            "title": e["title"],
            "link": e["link"],
            "unique_id": e["id"],
        }

        summary = e.get("summary")
        content = e.get("content")
        if content and len(content) > 0:
            content = content[0].get("value")

        if content:
            # prefer use content as description
            item["description"] = content
            item["content"] = content
        elif summary:
            item["description"] = summary
        else:
            item["description"] = ""

        author_detail = (
            e.get("author_detail")
            if e.get("author_detail")
            else feed.get("author_detail")
        )
        if author_detail:
            item["author_name"] = author_detail.get("name")
            item["author_email"] = author_detail.get("email")
            item["author_link"] = author_detail.get("href")
        elif e.get("author"):
            item["author_name"] = e.get("author")
        elif feed.get("author"):
            item["author_name"] = feed.get("author")

        update = e.get("updated_parsed")
        if update:
            item["update"] = datetime.datetime(*update[:6])

        pubdate = e.get("published_parsed") if e.get("published_parsed") else update
        if pubdate:
            item["pubdate"] = datetime.datetime(*pubdate[:6])
        else:
            item["pubdate"] = datetime.datetime.now()

        logger.debug(f"item: {item}")
        return item

    def _generate_feed(
        self, gen_cls: Type[SyndicationFeed], items: List[dict]
    ) -> SyndicationFeed:
        feed = gen_cls(
            title=self.title,
            link=self.home_page_url,
            description=self.description,
            feed_url=self.feed_url,
            author_name=self.author_name,
            author_link=self.author_link,
        )
        for i in items:
            feed.add_item(**i)
        return feed