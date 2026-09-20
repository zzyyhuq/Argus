import arxiv


class ArxivSearch:
    """
    Arxiv API retriever
    """
    def __init__(self, query, sort='Relevance', query_domains=None):
        self.arxiv = arxiv
        self.query = query
        assert sort in ['Relevance', 'SubmittedDate'], "Invalid sort criterion"
        self.sort = arxiv.SortCriterion.SubmittedDate if sort == 'SubmittedDate' else arxiv.SortCriterion.Relevance
        

    def search(self, max_results=5):
        """
        执行搜索
        :param query:
        :param max_results:
        :return:
        """
        try:
            arxiv_gen = list(arxiv.Client().results(
                self.arxiv.Search(
                    query=self.query,
                    max_results=max_results,
                    sort_by=self.sort,
                )
            ))
        except Exception as e:
            print(f"Error: {e}. Failed fetching arXiv sources. Resulting in empty response.")
            return []

        search_result = []
        for result in arxiv_gen:
            # 不完整的 arxiv.Result 对象可能让 title/pdf_url/summary 变成 None。
            # 跳过没有可用 href 的条目，其余字段给默认值，
            # 避免单条不完整的命中把归一化逻辑搞崩。
            href = getattr(result, "pdf_url", None) or getattr(result, "entry_id", None)
            if not href:
                continue
            title = getattr(result, "title", None) or ""
            body = getattr(result, "summary", None) or ""
            search_result.append({
                "title": title,
                "href": href,
                "body": body,
            })

        return search_result
