import os
from ..utils import check_pkg


class ExaSearch:
    """
    Exa API retriever
    """

    def __init__(self, query, query_domains=None):
        """
        初始化 ExaSearch 对象。
        参数：
            query: 搜索查询。
        """
        # 这个校验是必要的，因为 exa_py 是可选依赖
        check_pkg("exa_py")
        from exa_py import Exa
        self.query = query
        self.api_key = self._retrieve_api_key()
        self.client = Exa(api_key=self.api_key)
        self.query_domains = query_domains or None

    def _retrieve_api_key(self):
        """
        从环境变量中读取 Exa API key。
        返回：
            API key。
        异常：
            Exception: 找不到 API key 时抛出。
        """
        try:
            api_key = os.environ["EXA_API_KEY"]
        except KeyError:
            raise Exception(
                "Exa API key not found. Please set the EXA_API_KEY environment variable. "
                "You can obtain your key from https://exa.ai/"
            )
        return api_key

    def search(
        self, max_results=10, use_autoprompt=False, search_type="neural", **filters
    ):
        """
        使用 Exa API 执行查询搜索。
        参数：
            max_results: 最多返回的结果数。
            use_autoprompt: 是否启用 autoprompt。
            search_type: 搜索类型（如 "neural"、"keyword"）。
            **filters: 附加过滤条件（如日期范围、域名）。
        返回：
            搜索结果列表。
        """
        try:
            results = self.client.search(
                self.query,
                type=search_type,
                use_autoprompt=use_autoprompt,
                num_results=max_results,
                include_domains=self.query_domains,
                **filters
            )
        except Exception as e:
            print(f"Error: {e}. Failed fetching sources from Exa. Empty response.")
            return []

        search_response = []
        rows = getattr(results, "results", None) or []
        if not isinstance(rows, list):
            return []
        for result in rows:
            href = getattr(result, "url", None)
            if not href:
                continue
            body = getattr(result, "text", None) or getattr(result, "summary", None) or ""
            search_response.append({"href": href, "body": body})
        return search_response

    def find_similar(self, url, exclude_source_domain=False, **filters):
        """
        使用 Exa API 查找与给定 URL 相似的文档。
        参数：
            url: 要查找相似文档的 URL。
            exclude_source_domain: 是否在结果中排除来源域名。
            **filters: 附加过滤条件。
        返回：
            相似文档列表。
        """
        results = self.client.find_similar(
            url, exclude_source_domain=exclude_source_domain, **filters
        )

        similar_response = []
        for result in results.results or []:
            href = getattr(result, "url", None)
            if not href:
                continue
            body = getattr(result, "text", None) or getattr(result, "summary", None) or ""
            similar_response.append({"href": href, "body": body})
        return similar_response

    def get_contents(self, ids, **options):
        """
        使用 Exa API 获取指定 ID 的内容。
        参数：
            ids: 要获取的文档 ID。
            **options: 内容获取的附加选项。
        返回：
            文档内容列表。
        """
        results = self.client.get_contents(ids, **options)

        contents_response = []
        for result in results.results or []:
            result_id = getattr(result, "id", None)
            if result_id is None:
                continue
            content = getattr(result, "text", None) or ""
            contents_response.append({"id": result_id, "content": content})
        return contents_response
