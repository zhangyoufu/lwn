#!/usr/bin/env python3
import dataclasses
import datetime
import email.utils
import json
import os
import pathlib
import re
import requests
import time
import xml.etree.ElementTree as ET

state_filename = 'state/articles.json'
rss_filename = 'gh-pages/rss.xml'
feed_url = os.environ.get('FEED_URL', 'https://zhangyoufu.github.io/lwn/rss.xml')
websub_hub_url = os.environ.get('WEBSUB_HUB_URL', 'https://pubsubhubbub.appspot.com/')

def http_get(url, expect=(200,), retry_count=3, retry_interval=15, **kwargs):
    print('GET', url)
    kwargs.setdefault('allow_redirects', False)
    for retry_idx in range(retry_count):
        try:
            rsp = requests.get(url, **kwargs)
            assert rsp.status_code in expect, f'unexpected HTTP response status code {rsp.status_code}'
            return rsp
        except Exception:
            if retry_idx == retry_count - 1:
                raise
            time.sleep(retry_interval)

month_names = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
month_idx = {s: i+1 for i, s in enumerate(month_names)}

def get_article_free_date(article_id: int, default: datetime.datetime) -> datetime.datetime:
    rsp = http_get(f'https://lwn.net/Articles/{article_id}/', expect=(200, 403))
    if rsp.status_code == 200:
        return default
    m = re.search(r'available on (?P<month>'+'|'.join(month_names)+r') (?P<day>[1-9]|[12][0-9]|3[01]), (?P<year>\d{4,})', rsp.text)
    # the unlock time is 00:00 UTC
    result = datetime.datetime(
        year=int(m.group('year')),
        month=month_idx[m.group('month')],
        day=int(m.group('day')),
        tzinfo = datetime.timezone.utc,
    )
    print('available on', result)
    return result

@dataclasses.dataclass
class Article:
	xml: ET.Element
	_pub_date_elem: ET.Element
	_title_elem: ET.Element
	id_: int

	def __init__(self, xml: ET.Element) -> None:
		self.xml = xml
		self._pub_date_elem = xml.find('pubDate')
		self._title_elem = self.xml.find('title')
		self.id_ = int(re.fullmatch(r'https://lwn\.net/Articles/(\d+)/', xml.find('link').text).group(1))

	@property
	def title(self) -> str:
		return self._title_elem.text

	@title.setter
	def title(self, value: str) -> None:
		self._title_elem.text = value

	@property
	def pub_date(self) -> datetime.datetime:
		return email.utils.parsedate_to_datetime(self._pub_date_elem.text)

	@pub_date.setter
	def pub_date(self, value: datetime.datetime) -> None:
		self._pub_date_elem.text = email.utils.format_datetime(value)

	@property
	def is_paid(self) -> bool:
		return self.title.startswith('[$] ')

	def resolve(self) -> None:
		title = self.title
		if title.startswith('[$] '):
			self.title = title[4:]
			self.pub_date = get_article_free_date(self.id_, self.pub_date)

local_articles: dict[int, Article] = {}

## load local state (if available)
state_path = pathlib.Path(state_filename)
if state_path.exists():
	for item in json.loads(state_path.read_bytes()):
		article = Article(ET.fromstring(item))
		local_articles[article.id_] = article

## load remote RSS feed
root = ET.fromstring(http_get('https://lwn.net/headlines/rss').text)
rss = root
assert rss.tag == 'rss'
assert rss.get('version') == '2.0'
assert len(rss) == 1
channel = rss[0]
assert channel.tag == 'channel'

## override feed URL
feed_link = channel.find('{http://www.w3.org/2005/Atom}link')
feed_link.set('href', feed_url)

## extract feed items, leave the skeleton
i = 0
while i < len(channel) and channel[i].tag != 'item':
	i += 1
j = i + 1
while j < len(channel) and channel[j].tag == 'item':
	j += 1
assert j == len(channel)
items = channel[i:]
del channel[i:]

## add WebSub Hub URL
ET.SubElement(channel, '{http://www.w3.org/2005/Atom}link', {'href': websub_hub_url, 'rel': 'hub'})

## RSS_output = remote_free_articles + local_available_articles
## local_articles -= expired_local_articles
## local_articles += remote_paid_articles_previously_unknown
now = datetime.datetime.now(datetime.timezone.utc)
local_article_expire = now + datetime.timedelta(days=3)
output = []
for item in items:
	remote_article = Article(item)
	article_id = remote_article.id_
	if not remote_article.is_paid:
		output.append((remote_article.pub_date, remote_article))
		local_articles.pop(article_id, None)
	else: # is_paid
		local_article = local_articles.get(article_id, None)
		if local_article is not None:
			# known
			if local_article.pub_date <= now:
				output.append((local_article.pub_date, local_article))
			if local_article_expire <= local_article.pub_date:
				del local_articles[article_id]
		else:
			remote_article.resolve()
			local_articles[article_id] = remote_article

## sort output items by pub_date
output.sort()

## add output items into RSS skeleton
for _, item in output:
	channel.append(item.xml)

## RSS output
ET.indent(root, space='\t')
pathlib.Path(rss_filename).write_bytes(ET.tostring(root, encoding='utf-8'))

## save state
state_path.write_text(json.dumps([
	ET.tostring(article.xml, encoding='unicode')
	for article in local_articles.values()
], ensure_ascii=False), encoding='utf-8-sig')
