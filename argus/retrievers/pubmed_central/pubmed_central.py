from typing import List, Dict, Any, Optional
import os
import xml.etree.ElementTree as ET
import requests


class PubMedCentralSearch:
    """
    PubMed Central 全文搜索
    """

    # PubMed Central 会在结果里内联返回全文，因此没有需要再抓取的内容。
    requires_scraping = False

    def __init__(self, query: str, query_domains=None):
        self.base_search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        self.base_fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        
        # 从环境变量读取 API key
        self.api_key = os.getenv('NCBI_API_KEY')
        if not self.api_key:
            print("Warning: NCBI_API_KEY not set. Requests will be rate-limited.")
        
        self.query = query
        self.db_type = os.getenv('PUBMED_DB', 'pmc')  # 默认用 PMC 以获取全文
        
        # 从环境变量读取的可选参数
        self.params = self._populate_params()

    def _populate_params(self) -> Dict[str, Any]:
        """
        从以 'PUBMED_ARG_' 开头的环境变量中读取参数
        """
        params = {
            key[len('PUBMED_ARG_'):].lower(): value
            for key, value in os.environ.items()
            if key.startswith('PUBMED_ARG_')
        }
        
        # 未提供时设置默认值
        params.setdefault('sort', 'relevance')
        params.setdefault('retmode', 'json')
        return params

    def _search_articles(self, max_results: int) -> Optional[List[str]]:
        """
        根据查询搜索文章 ID
        """
        # 构造带全文过滤条件的搜索查询
        if self.db_type == 'pubmed':
            search_term = f"{self.query} AND (ffrft[filter] OR pmc[filter])"
        else:  # PMC 里始终有全文
            search_term = self.query
        
        search_params = {
            "db": self.db_type,
            "term": search_term,
            "retmax": max_results,
            "api_key": self.api_key,
            **self.params  # 带上自定义参数
        }
        
        try:
            response = requests.get(self.base_search_url, params=search_params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return []

            # 出错或异常响应可能把 esearchresult 设为 null、list，或干脆没有
            # idlist。只有真正的 list 才算成功。
            esearch = data.get("esearchresult")
            if not isinstance(esearch, dict):
                return []
            id_list = esearch.get("idlist") or []
            if not isinstance(id_list, list):
                return []
            print(f"Found {len(id_list)} articles with full text available")
            return id_list
            
        except requests.RequestException as e:
            print(f"Failed to search articles: {e}")
            return None

    def _fetch_full_text(self, article_id: str) -> Optional[Dict[str, str]]:
        """
        获取单篇文章的全文
        """
        fetch_params = {
            "db": "pmc" if self.db_type == "pmc" else "pmc",  # 始终从 PMC 获取全文
            "id": article_id,
            "rettype": "full",
            "retmode": "xml",
            "api_key": self.api_key
        }
        
        try:
            response = requests.get(self.base_fetch_url, params=fetch_params)
            response.raise_for_status()
            
            # 解析 XML 内容
            try:
                root = ET.fromstring(response.text)
                
                # 提取标题（用 itertext 以包含嵌套的格式标签）
                title = root.find('.//article-title')
                title_text = (
                    " ".join(title.itertext()).strip() if title is not None else ""
                )
                
                # 提取摘要
                abstract = root.find('.//abstract')
                abstract_text = " ".join(abstract.itertext()) if abstract is not None else ""
                
                # 提取正文
                body = root.find('.//body')
                body_text = " ".join(body.itertext()) if body is not None else ""
                
                # 合并所有文本内容
                full_content = f"Title: {title_text}\n\nAbstract: {abstract_text}\n\nBody: {body_text}"
                
                # 构造 URL
                if self.db_type == "pmc" or article_id.startswith("PMC"):
                    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{article_id}/"
                else:
                    url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{article_id}/"
                
                return {
                    "href": url,
                    "url": url,
                    "body": full_content,
                    "raw_content": full_content,
                    "title": title_text
                }
                
            except ET.ParseError as e:
                return None
                
        except requests.RequestException as e:
            return None

    def search(self, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        执行搜索并获取全文内容。

        :param max_results: 最多返回的结果数
        :return: 如下格式的 JSON 响应：
            [
              {
                "url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/",
                "raw_content": "Full text content of the article..."
              },
              ...
            ]
        """
        # 第 1 步：搜索文章 ID。始终返回 list（绝不返回 None）：
        # 像 actions.query_processing.get_search_results 这样的调用方标注了
        # -> List[Dict]，而 skills.researcher 会对 search_results 取 len()，
        # 遇到 None 会抛 TypeError。
        article_ids = self._search_articles(max_results)
        if not article_ids:
            return []
        
        # 第 2 步：逐篇获取全文
        results = []
        for article_id in article_ids:
            article_content = self._fetch_full_text(article_id)
            if article_content:
                results.append(article_content)
        
        return results