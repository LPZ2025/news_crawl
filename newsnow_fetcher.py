"""
NewsNow 新闻爬取模块

重新实现从 newsnow API 获取新闻的逻辑
基于原有 main.py 中的 DataFetcher 类，但独立封装，便于维护和扩展
"""

import json
import random
import re
import time
import yaml
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union
from datetime import datetime
import pytz
import requests


class NewsNowFetcher:
    """
    NewsNow 新闻爬取器
    
    功能：
    1. 从 newsnow API 获取单个平台的新闻数据
    2. 支持批量爬取多个平台
    3. 自动重试机制
    4. 请求间隔控制（避免频繁请求）
    """
    
    def __init__(self, proxy_url: Optional[str] = None):
        """
        初始化爬取器
        
        Args:
            proxy_url: 代理地址，格式如 "http://127.0.0.1:10086"
                       如果为 None，则不使用代理
        """
        self.proxy_url = proxy_url
        # newsnow API 的基础地址
        self.base_url = "https://newsnow.busiyi.world/api/s"
    
    def fetch_custom_api(
        self,
        platform_config: Dict,
    ) -> Tuple[Optional[Dict], str, str]:
        """
        从自定义 API 获取新闻数据（完全基于配置）
        
        Args:
            platform_config: 平台配置字典，包含所有配置项
        
        Returns:
            Tuple[Optional[Dict], str, str]:
            - 解析后的新闻数据字典（转换为标准格式），失败返回 None
            - 平台ID
            - 平台名称
        """
        platform_id = platform_config.get("id")
        platform_name = platform_config.get("name", platform_id)
        api_url = platform_config.get("api_url")
        
        if not api_url:
            print(f"❌ 平台 {platform_id} 缺少 api_url 配置")
            return None, platform_id, platform_name
        
        # 读取请求配置
        request_config = platform_config.get("request", {})
        method = request_config.get("method", "GET").upper()
        timeout = request_config.get("timeout", 10)
        custom_headers = request_config.get("headers", {})
        
        # 默认请求头
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
        # 合并自定义请求头（自定义的会覆盖默认的）
        headers = {**default_headers, **custom_headers}
        
        # 读取重试配置
        retry_config = platform_config.get("retry", {})
        max_retries = retry_config.get("max_retries", 2)
        min_retry_wait = retry_config.get("min_retry_wait", 3)
        max_retry_wait = retry_config.get("max_retry_wait", 5)
        
        # 读取调试配置
        debug_config = platform_config.get("debug", {})
        debug_enabled = debug_config.get("enabled", False)
        
        proxies = None
        if self.proxy_url:
            proxies = {"http": self.proxy_url, "https": self.proxy_url}
        
        retries = 0
        while retries <= max_retries:
            try:
                # 发送请求
                if method == "POST":
                    body = request_config.get("body")
                    response = requests.post(
                        api_url,
                        proxies=proxies,
                        headers=headers,
                        json=body if isinstance(body, dict) else None,
                        data=body if not isinstance(body, dict) else None,
                        timeout=timeout
                    )
                else:
                    response = requests.get(
                        api_url,
                        proxies=proxies,
                        headers=headers,
                        timeout=timeout
                    )
                
                response.raise_for_status()
                data_json = json.loads(response.text)
                
                # 尝试将自定义 API 的响应转换为标准格式
                standardized_data = self._standardize_custom_api_response(
                    data_json, 
                    platform_id,
                    platform_config=platform_config
                )
                
                # 输出结果
                items_count = len(standardized_data.get("items", []))
                print(f"✅ 获取自定义API {platform_id} ({platform_name}) 成功，解析到 {items_count} 条数据")
                
                # 调试信息（基于配置）
                if debug_enabled and items_count == 0:
                    print(f"⚠️ 调试：{platform_id}解析后数据为空")
                
                return standardized_data, platform_id, platform_name
                
            except Exception as e:
                retries += 1
                if retries <= max_retries:
                    base_wait = random.uniform(min_retry_wait, max_retry_wait)
                    additional_wait = (retries - 1) * random.uniform(1, 2)
                    wait_time = base_wait + additional_wait
                    print(f"⚠️ 请求自定义API {platform_id} 失败: {e}. {wait_time:.2f}秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"❌ 请求自定义API {platform_id} 失败，已重试 {max_retries} 次: {e}")
                    return None, platform_id, platform_name
        
        return None, platform_id, platform_name
    
    def _standardize_custom_api_response(
        self, 
        data: Union[Dict, List], 
        platform_id: str,
        platform_config: Dict
    ) -> Dict:
        """
        将自定义 API 的响应转换为标准格式（完全基于配置）
        
        Args:
            data: API 返回的原始数据
            platform_id: 平台ID
            platform_config: 平台配置字典
        
        标准格式：
        {
            "status": "success",
            "id": "platform_id",
            "items": [
                {
                    "title": "新闻标题",
                    "url": "https://...",
                    "pubDate": 时间戳或时间字符串
                }
            ]
        }
        """
        standardized = {
            "status": "success",
            "id": platform_id,
            "items": []
        }
        
        # 优先检查：如果数据已经是标准格式，直接返回（不需要 field_mapping）
        if isinstance(data, dict) and "items" in data and isinstance(data.get("items"), list):
            # 验证 items 中的元素是否包含 title 字段（标准格式的基本要求）
            items_list = data.get("items", [])
            if len(items_list) == 0 or (len(items_list) > 0 and isinstance(items_list[0], dict) and "title" in items_list[0]):
                # 更新 id 字段（使用配置的 platform_id）
                data["id"] = platform_id
                return data
        
        # 读取数据解析配置
        data_parsing_config = platform_config.get("data_parsing", {})
        data_path = data_parsing_config.get("data_path")
        fallback_enabled = data_parsing_config.get("fallback_enabled", True)
        fallback_fields = data_parsing_config.get("fallback_fields", ["data", "list", "items", "result"])
        
        # 读取字段映射配置（非标准格式需要字段映射）
        field_mapping = platform_config.get("field_mapping", {})
        if not field_mapping:
            print(f"⚠️ 警告：平台 {platform_id} 没有配置字段映射，且数据不是标准格式，跳过解析")
            return standardized
        
        # 读取URL构建配置
        url_builder_config = platform_config.get("url_builder", {})
        base_url = url_builder_config.get("base_url")
        url_template = url_builder_config.get("template", "{base_url}/{itemId}")
        
        # 读取调试配置
        debug_config = platform_config.get("debug", {})
        debug_enabled = debug_config.get("enabled", False)
        
        # 尝试多种常见的数据格式（获取数据列表）
        items = []
        
        # 如果指定了 data_path，优先使用它
        if data_path and isinstance(data, dict):
            # 支持嵌套路径，如 "templateMaterial" 或 "data.items"
            path_parts = data_path.split(".")
            current_data = data
            for part in path_parts:
                if isinstance(current_data, dict) and part in current_data:
                    current_data = current_data[part]
                else:
                    current_data = None
                    break
            
            if isinstance(current_data, list):
                items = current_data
            elif current_data is not None:
                print(f"⚠️ 警告：data_path '{data_path}' 指向的不是列表类型")
        
        # 如果没有通过 data_path 找到数据，且启用了 fallback，尝试常见格式
        if len(items) == 0 and fallback_enabled:
            # 格式1: 直接是数组
            if isinstance(data, list):
                items = data
            # 尝试 fallback 字段列表
            elif isinstance(data, dict):
                for field in fallback_fields:
                    if field in data and isinstance(data[field], list):
                        items = data[field]
                        break
        
        # 调试信息（基于配置）
        if debug_enabled and len(items) == 0:
            print(f"⚠️ 调试：{platform_id}未找到数据列表")
        
        # 获取字段映射配置
        title_field = field_mapping.get("title")  # 标题字段名（可能包含嵌套路径，如 "templateMaterial.widgetTitle"）
        time_field = field_mapping.get("publishTime")  # 时间字段名（可能包含嵌套路径）
        item_id_field = field_mapping.get("itemId")  # ID字段名（可能包含嵌套路径）
        
        # 辅助函数：从嵌套路径获取值
        def get_nested_value(obj: dict, path: str):
            """从嵌套路径获取值，如 'templateMaterial.widgetTitle'"""
            if not path:
                return None
            parts = path.split(".")
            current = obj
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            return current
        
        # 转换每个 item 为标准格式
        for item in items:
            if not isinstance(item, dict):
                continue
            
            standardized_item = {}
            
            # 提取标题（支持嵌套路径）
            if title_field:
                title_value = get_nested_value(item, title_field)
                if title_value:
                    standardized_item["title"] = str(title_value).strip()
            
            # 提取发布时间（支持嵌套路径）
            if time_field:
                time_value = get_nested_value(item, time_field)
                if time_value:
                    standardized_item["pubDate"] = time_value
            
            # 构建完整URL（使用配置的模板，支持嵌套路径）
            if item_id_field:
                item_id = get_nested_value(item, item_id_field)
                if item_id:
                    if base_url:
                        # 使用配置的URL模板构建URL
                        # 支持 {base_url} 和 {itemId} 占位符
                        full_url = url_template.replace("{base_url}", base_url.rstrip("/"))
                        full_url = full_url.replace("{itemId}", str(item_id).lstrip("/"))
                        standardized_item["url"] = full_url
                    else:
                        # 如果没有base_url，直接使用itemId作为URL
                        standardized_item["url"] = str(item_id)
            
            # 只有标题存在才添加
            if "title" in standardized_item:
                standardized["items"].append(standardized_item)
        
        return standardized
    
    def fetch_single_platform(
        self,
        platform_id: str,
        platform_name: Optional[str] = None,
        max_retries: int = 2,
        min_retry_wait: int = 3,
        max_retry_wait: int = 5,
    ) -> Tuple[Optional[Dict], str, str]:
        """
        从 NewsNow API 获取单个平台的新闻数据
        
        专门用于 NewsNow 平台的爬取，不处理自定义 API
        
        Args:
            platform_id: 平台ID，如 "zhihu"、"weibo"、"douyin" 等
            platform_name: 平台名称（可选），用于显示，如 "知乎"、"微博"
            max_retries: 最大重试次数，默认2次（总共尝试3次）
            min_retry_wait: 重试等待时间的最小值（秒）
            max_retry_wait: 重试等待时间的最大值（秒）
        
        Returns:
            Tuple[Optional[Dict], str, str]:
            - 第一个元素：解析后的新闻数据字典，失败返回 None
            - 第二个元素：平台ID
            - 第三个元素：平台名称（如果有）
        
        数据结构说明：
            返回的字典格式：
            {
                "status": "success" 或 "cache",
                "id": "zhihu",
                "updatedTime": 1234567890,
                "items": [
                    {
                        "title": "新闻标题",
                        "url": "https://...",
                        "mobileUrl": "https://...",
                        ...
                    },
                    ...
                ]
            }
        """
        # 如果没有提供平台名称，使用平台ID作为名称
        if platform_name is None:
            platform_name = platform_id
        
        # 使用 newsnow API
        # 构造 API 请求 URL
        # 格式：https://newsnow.busiyi.world/api/s?id=平台ID&latest
        # latest 参数表示获取最新数据
        url = f"{self.base_url}?id={platform_id}&latest"
        
        # 配置代理（如果需要）
        proxies = None
        if self.proxy_url:
            proxies = {
                "http": self.proxy_url,
                "https": self.proxy_url
            }
        
        # 设置 HTTP 请求头
        # 模拟浏览器请求，避免被服务器拒绝
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }
        
        # 重试循环
        retries = 0
        while retries <= max_retries:
            try:
                # 发送 HTTP GET 请求
                # timeout=10 表示10秒超时
                response = requests.get(
                    url,
                    proxies=proxies,
                    headers=headers,
                    timeout=10
                )
                
                # 检查 HTTP 状态码，如果不是 2xx，会抛出异常
                response.raise_for_status()
                
                # 解析 JSON 响应
                data_json = json.loads(response.text)
                
                # 检查响应状态
                # newsnow API 返回的 status 字段：
                # - "success": 最新数据
                # - "cache": 缓存数据
                # - 其他值：异常状态
                status = data_json.get("status", "未知")
                if status not in ["success", "cache"]:
                    raise ValueError(f"响应状态异常: {status}")
                
                # 打印成功信息
                status_info = "最新数据" if status == "success" else "缓存数据"
                print(f"✅ 获取 {platform_id} ({platform_name}) 成功（{status_info}）")
                
                # 返回解析后的数据
                return data_json, platform_id, platform_name
                
            except Exception as e:
                # 请求失败，准备重试
                retries += 1
                
                if retries <= max_retries:
                    # 计算等待时间
                    # 基础等待时间：随机在 min_retry_wait 和 max_retry_wait 之间
                    base_wait = random.uniform(min_retry_wait, max_retry_wait)
                    # 额外等待时间：随着重试次数增加而增加
                    additional_wait = (retries - 1) * random.uniform(1, 2)
                    wait_time = base_wait + additional_wait
                    
                    print(f"⚠️ 请求 {platform_id} 失败: {e}. {wait_time:.2f}秒后重试...")
                    time.sleep(wait_time)
                else:
                    # 重试次数用尽，返回失败
                    print(f"❌ 请求 {platform_id} 失败，已重试 {max_retries} 次: {e}")
                    return None, platform_id, platform_name
        
        # 理论上不会执行到这里，但为了安全起见
        return None, platform_id, platform_name
    
    def _process_news_items(
        self,
        data_json: Dict,
        platform_id: str,
        results: Dict,
    ) -> None:
        """
        处理新闻数据项（通用方法，用于 newsnow 和自定义 API）
        
        Args:
            data_json: 标准格式的新闻数据字典
            platform_id: 平台ID
            results: 结果字典（会被修改）
        """
        try:
            # 初始化该平台的结果字典
            results[platform_id] = {}
            
            # 获取新闻列表
            items = data_json.get("items", [])
            
            # 遍历每条新闻
            for index, item in enumerate(items, 1):
                # 获取标题
                title = item.get("title")
                
                # 跳过无效标题
                if title is None or isinstance(title, float) or not str(title).strip():
                    continue
                
                # 清理标题（去除首尾空格）
                title = str(title).strip()
                
                # 获取链接
                url = item.get("url", "")
                mobile_url = item.get("mobileUrl", "")
                
                # 获取发布时间
                pub_date = item.get("pubDate")
                publish_time = None
                
                if pub_date:
                    try:
                        # 如果是时间戳（毫秒）
                        if isinstance(pub_date, (int, float)):
                            # 转换为秒（如果是毫秒）
                            if pub_date > 1e10:  # 大于10位数，可能是毫秒
                                pub_date = pub_date / 1000
                            publish_time = datetime.fromtimestamp(pub_date, tz=pytz.timezone("Asia/Shanghai"))
                        # 如果是时间字符串，尝试解析
                        elif isinstance(pub_date, str):
                            # 尝试多种时间格式
                            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"]:
                                try:
                                    publish_time = datetime.strptime(pub_date, fmt)
                                    publish_time = pytz.timezone("Asia/Shanghai").localize(publish_time)
                                    break
                                except:
                                    continue
                    except Exception:
                        publish_time = None
                
                # 如果没有时间信息，使用当前时间
                if publish_time is None:
                    publish_time = datetime.now(pytz.timezone("Asia/Shanghai"))
                
                # 处理重复标题
                if title in results[platform_id]:
                    # 标题已存在，只添加排名
                    results[platform_id][title]["ranks"].append(index)
                    # 如果新时间更早，更新发布时间（保留最早的发布时间）
                    if publish_time < results[platform_id][title].get("publishTime", publish_time):
                        results[platform_id][title]["publishTime"] = publish_time
                else:
                    # 新标题，创建新记录
                    results[platform_id][title] = {
                        "ranks": [index],
                        "url": url,
                        "mobileUrl": mobile_url,
                        "publishTime": publish_time,
                    }
        except Exception as e:
            print(f"❌ 处理 {platform_id} 数据出错: {e}")
            raise
    
    def _fetch_newsnow_platforms(
        self,
        newsnow_platforms: List[Union[str, Tuple[str, str]]],
        request_interval: int = 1000,
    ) -> Tuple[Dict, Dict, List]:
        """
        专门处理 newsnow 平台的爬取逻辑
        
        Args:
            newsnow_platforms: newsnow 平台列表，格式：["zhihu"] 或 [("zhihu", "知乎")]
            request_interval: 请求间隔（毫秒）
        
        Returns:
            Tuple[Dict, Dict, List]: (results, id_to_name, failed_ids)
        """
        results = {}
        id_to_name = {}
        failed_ids = []
        
        print(f"\n📰 开始爬取 {len(newsnow_platforms)} 个 NewsNow 平台...")
        
        for i, platform_info in enumerate(newsnow_platforms):
            # 解析平台信息
            if isinstance(platform_info, tuple):
                platform_id, platform_name = platform_info
            else:
                platform_id = platform_info
                platform_name = platform_id
            
            if not platform_id:
                print(f"⚠️ 跳过无效的 NewsNow 平台配置: {platform_info}")
                continue
            
            id_to_name[platform_id] = platform_name
            
            # 调用 newsnow API
            data_json, _, _ = self.fetch_single_platform(platform_id, platform_name)
            
            # 处理返回的数据
            if data_json:
                try:
                    self._process_news_items(data_json, platform_id, results)
                except Exception as e:
                    print(f"❌ 处理 NewsNow 平台 {platform_id} 失败: {e}")
                    failed_ids.append(platform_id)
            else:
                failed_ids.append(platform_id)
            
            # 控制请求间隔
            if i < len(newsnow_platforms) - 1:
                actual_interval = request_interval + random.randint(-10, 20)
                actual_interval = max(50, actual_interval)
                time.sleep(actual_interval / 1000)
        
        print(f"✅ NewsNow 平台爬取完成：成功 {len(results)} 个，失败 {len(failed_ids)} 个")
        return results, id_to_name, failed_ids
    
    def _fetch_custom_platforms(
        self,
        custom_platforms: List[Dict],
        request_interval: int = 1000,
    ) -> Tuple[Dict, Dict, List]:
        """
        专门处理自定义 API 平台的爬取逻辑
        
        Args:
            custom_platforms: 自定义平台列表，格式：[{"id": "36kr", "name": "36氪", "api_url": "...", ...}]
            request_interval: 请求间隔（毫秒）
        
        Returns:
            Tuple[Dict, Dict, List]: (results, id_to_name, failed_ids)
        """
        results = {}
        id_to_name = {}
        failed_ids = []
        
        print(f"\n🔧 开始爬取 {len(custom_platforms)} 个自定义 API 平台...")
        
        for i, platform_config in enumerate(custom_platforms):
            platform_id = platform_config.get("id")
            platform_name = platform_config.get("name", platform_id)
            api_url = platform_config.get("api_url")
            
            if not platform_id or not api_url:
                print(f"⚠️ 跳过无效的自定义平台配置: {platform_config}")
                continue
            
            id_to_name[platform_id] = platform_name
            
            # 调用自定义 API（传递完整配置）
            data_json, _, _ = self.fetch_custom_api(platform_config=platform_config)
            
            # 处理返回的数据
            if data_json:
                try:
                    self._process_news_items(data_json, platform_id, results)
                except Exception as e:
                    print(f"❌ 处理自定义平台 {platform_id} 失败: {e}")
                    failed_ids.append(platform_id)
            else:
                failed_ids.append(platform_id)
            
            # 控制请求间隔
            if i < len(custom_platforms) - 1:
                actual_interval = request_interval + random.randint(-10, 20)
                actual_interval = max(50, actual_interval)
                time.sleep(actual_interval / 1000)
        
        print(f"✅ 自定义 API 平台爬取完成：成功 {len(results)} 个，失败 {len(failed_ids)} 个")
        return results, id_to_name, failed_ids
    
    def crawl_multiple_platforms(
        self,
        platforms: List[Union[str, Tuple[str, str], Dict]],
        request_interval: int = 1000,
    ) -> Tuple[Dict, Dict, List]:
        """
        批量爬取多个平台的新闻数据
        
        将平台分为两类：
        1. NewsNow 平台：使用 newsnow API
        2. 自定义 API 平台：使用用户配置的 API
        
        两类平台同时运行，结果合并后返回
        
        Args:
            platforms: 平台列表，可以是：
                      - 字符串列表：["zhihu", "weibo"]
                      - 元组列表：[("zhihu", "知乎"), ("weibo", "微博")]
                      - 字典列表：[{"id": "36kr", "name": "36氪", "api_url": "https://..."}]
            request_interval: 请求间隔（毫秒），默认1000毫秒（1秒）
        
        Returns:
            Tuple[Dict, Dict, List]:
            - results: 新闻数据字典（合并后的结果）
            - id_to_name: 平台ID到名称的映射（合并后的结果）
            - failed_ids: 失败的平台ID列表（合并后的结果）
        """
        # 分离 NewsNow 平台和自定义 API 平台
        newsnow_platforms = []
        custom_platforms = []
        
        for platform_info in platforms:
            if isinstance(platform_info, dict) and "api_url" in platform_info:
                # 自定义 API 平台
                custom_platforms.append(platform_info)
            else:
                # NewsNow 平台
                newsnow_platforms.append(platform_info)
        
        # 分别爬取两类平台
        newsnow_results = {}
        newsnow_id_to_name = {}
        newsnow_failed_ids = []
        
        custom_results = {}
        custom_id_to_name = {}
        custom_failed_ids = []

        # 先爬取自定义 API 平台
        if custom_platforms:
            custom_results, custom_id_to_name, custom_failed_ids = self._fetch_custom_platforms(
                custom_platforms, request_interval
            )
        # 再爬取 NewsNow 平台
        if newsnow_platforms:
            newsnow_results, newsnow_id_to_name, newsnow_failed_ids = self._fetch_newsnow_platforms(
                newsnow_platforms, request_interval
            )
        
        # 合并结果
        results = {**newsnow_results, **custom_results}
        id_to_name = {**newsnow_id_to_name, **custom_id_to_name}
        failed_ids = newsnow_failed_ids + custom_failed_ids
        
        # 打印最终结果摘要
        success_count = len(results)
        failed_count = len(failed_ids)
        print(f"\n📊 全部爬取完成：成功 {success_count} 个平台，失败 {failed_count} 个平台")
        if results:
            print(f"✅ 成功平台: {list(results.keys())}")
        if failed_ids:
            print(f"❌ 失败平台: {failed_ids}")
        
        return results, id_to_name, failed_ids
    
    def load_config(self, config_path: str = None) -> List[Union[Tuple[str, str], Dict]]:
        """
        从配置文件加载平台列表
        
        支持新的分离格式：
        1. newsnow_platforms: NewsNow 平台列表
        2. custom_platforms: 自定义 API 平台列表
        
        同时保持向后兼容（如果存在旧的 platforms 格式）
        
        Args:
            config_path: 配置文件路径，默认为 utils/config.yaml
        
        Returns:
            平台列表，格式：[(id, name), ...] 或 [{"id": "...", "name": "...", "api_url": "..."}, ...]
        """
        if config_path is None:
            # 默认配置文件路径：utils/config.yaml
            current_file = Path(__file__)
            config_path = current_file.parent / "config.yaml"
        
        if not Path(config_path).exists():
            raise FileNotFoundError(f"配置文件 {config_path} 不存在")
        
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f)
        
        platforms = []
        
        # 优先使用新的分离格式
        if "newsnow_platforms" in config_data or "custom_platforms" in config_data:
            # 处理 NewsNow 平台
            newsnow_platforms_config = config_data.get("newsnow_platforms", [])
            for platform in newsnow_platforms_config:
                if "name" in platform:
                    platforms.append((platform["id"], platform["name"]))
                else:
                    platforms.append((platform["id"], platform["id"]))
            
            # 处理自定义 API 平台（读取完整配置结构）
            custom_platforms_config = config_data.get("custom_platforms", [])
            for platform in custom_platforms_config:
                # 直接使用平台配置字典（包含所有配置项）
                platform_dict = dict(platform)  # 复制整个配置
                platforms.append(platform_dict)
        
        # 向后兼容：如果存在旧的 platforms 格式，也处理它
        elif "platforms" in config_data:
            platforms_config = config_data.get("platforms", [])
            for platform in platforms_config:
                # 如果有 api_url，使用字典格式（自定义 API）
                if "api_url" in platform:
                    # 将旧格式转换为新格式
                    platform_dict = {
                        "id": platform["id"],
                        "name": platform.get("name", platform["id"]),
                        "api_url": platform["api_url"]
                    }
                    # 字段映射
                    if "field_mapping" in platform:
                        platform_dict["field_mapping"] = platform["field_mapping"]
                    # 数据解析配置（旧格式的 data_path）
                    if "data_path" in platform:
                        platform_dict["data_parsing"] = {"data_path": platform["data_path"]}
                    # URL构建配置（旧格式的 base_url）
                    if "base_url" in platform:
                        platform_dict["url_builder"] = {
                            "base_url": platform["base_url"],
                            "template": "{base_url}/{itemId}"
                        }
                    
                    platforms.append(platform_dict)
                # 否则使用元组格式（newsnow API）
                else:
                    if "name" in platform:
                        platforms.append((platform["id"], platform["name"]))
                    else:
                        platforms.append((platform["id"], platform["id"]))
        else:
            raise ValueError("配置文件中未找到 platforms、newsnow_platforms 或 custom_platforms 配置项")
        
        return platforms
    
    def save_to_file(
        self,
        results: Dict,
        id_to_name: Dict,
        failed_ids: List,
        output_base_dir: str = "output"
    ) -> str:
        """
        保存爬取结果到文件（按照原有逻辑构建快照）
        
        Args:
            results: 新闻数据字典
            id_to_name: 平台ID到名称的映射
            failed_ids: 失败的平台ID列表
            output_base_dir: 输出基础目录，默认为 output
        
        Returns:
            保存的文件路径
        """
        # 获取北京时间
        beijing_tz = pytz.timezone("Asia/Shanghai")
        beijing_time = datetime.now(beijing_tz)
        
        # 格式化日期文件夹：2025年11月29日
        date_folder = beijing_time.strftime("%Y年%m月%d日")
        
        # 格式化时间文件名：10时30分
        time_filename = beijing_time.strftime("%H时%M分")
        
        # 构建完整路径：output/2025年11月29日/txt/10时30分.txt
        output_dir = Path(output_base_dir) / date_folder / "txt"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = output_dir / f"{time_filename}.txt"
        
        # 清理标题中的特殊字符
        def clean_title(title: str) -> str:
            if not isinstance(title, str):
                title = str(title)
            cleaned_title = title.replace("\n", " ").replace("\r", " ")
            # 去除多余空格
            cleaned_title = re.sub(r"\s+", " ", cleaned_title)
            return cleaned_title.strip()
        
        # 写入文件
        with open(file_path, "w", encoding="utf-8") as f:
            for id_value, title_data in results.items():
                # 写入平台标识：id | name 或 id
                name = id_to_name.get(id_value)
                if name and name != id_value:
                    f.write(f"{id_value} | {name}\n")
                else:
                    f.write(f"{id_value}\n")
                
                # 按排名排序标题
                sorted_titles = []
                for title, info in title_data.items():
                    cleaned_title = clean_title(title)
                    if isinstance(info, dict):
                        ranks = info.get("ranks", [])
                        url = info.get("url", "")
                        mobile_url = info.get("mobileUrl", "")
                        publish_time = info.get("publishTime")
                    else:
                        ranks = info if isinstance(info, list) else []
                        url = ""
                        mobile_url = ""
                        publish_time = None
                    
                    # 如果没有时间，使用当前时间
                    if publish_time is None:
                        beijing_tz = pytz.timezone("Asia/Shanghai")
                        publish_time = datetime.now(beijing_tz)
                    
                    rank = ranks[0] if ranks else 1
                    sorted_titles.append((rank, cleaned_title, url, mobile_url, publish_time))
                
                # 按排名排序
                sorted_titles.sort(key=lambda x: x[0])
                
                # 写入每条新闻
                for rank, cleaned_title, url, mobile_url, publish_time in sorted_titles:
                    # 格式化时间：2025-11-30 09:52:02
                    time_str = publish_time.strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 构建行：时间 标题 [URL:链接] [MOBILE:链接]
                    line = f"{time_str} {cleaned_title}"
                    
                    # 如果有 mobileUrl 和 url，两个都保存；如果没有 mobileUrl，只保存 url
                    if url:
                        line += f" [URL:{url}]"
                    if mobile_url:
                        line += f" [MOBILE:{mobile_url}]"
                    
                    f.write(line + "\n")
                
                f.write("\n")
            
            # 写入失败的平台
            if failed_ids:
                f.write("==== 以下ID请求失败 ====\n")
                for id_value in failed_ids:
                    f.write(f"{id_value}\n")
        
        return str(file_path)
    
    def crawl_from_config(
        self,
        config_path: str = None,
        request_interval: int = 1000,
        output_base_dir: str = "output"
    ) -> Tuple[Dict, Dict, List, str]:
        """
        从配置文件读取平台列表并爬取，然后保存到文件
        
        Args:
            config_path: 配置文件路径，默认为 utils/config.yaml
            request_interval: 请求间隔（毫秒）
            output_base_dir: 输出基础目录，默认为 output
        
        Returns:
            Tuple[Dict, Dict, List, str]:
            - results: 新闻数据字典
            - id_to_name: 平台ID到名称的映射
            - failed_ids: 失败的平台ID列表
            - file_path: 保存的文件路径
        """
        # 1. 从配置文件加载平台列表
        platforms = self.load_config(config_path)
        print(f"📋 从配置文件加载了 {len(platforms)} 个平台")
        
        # 2. 批量爬取
        results, id_to_name, failed_ids = self.crawl_multiple_platforms(
            platforms=platforms,
            request_interval=request_interval
        )
        
        # 3. 保存到文件
        file_path = self.save_to_file(
            results=results,
            id_to_name=id_to_name,
            failed_ids=failed_ids,
            output_base_dir=output_base_dir
        )
        
        print(f"💾 数据已保存到: {file_path}")
        
        return results, id_to_name, failed_ids, file_path


if __name__ == "__main__":
    """
    新闻爬取主入口
    从配置文件读取平台列表，爬取所有新闻并保存到 output 目录
    """
    print("="*60)
    print("NewsNow 新闻爬取 - 股票分析文章生成模块")
    print("="*60)
    
    # 创建爬取器实例
    # 如果需要代理，可以这样：
    # fetcher = NewsNowFetcher(proxy_url="http://127.0.0.1:10086")
    fetcher = NewsNowFetcher()
    
    # 配置文件路径（相对于当前文件）
    config_path = Path(__file__).parent / "config.yaml"
    
    print(f"\n📁 配置文件: {config_path}")
    print(f"📁 输出目录: output/")
    print("\n开始爬取...\n")
    
    try:
        # 从配置文件读取并爬取，然后保存
        results, id_to_name, failed_ids, file_path = fetcher.crawl_from_config(
            config_path=str(config_path),
            request_interval=1000,  # 请求间隔1秒
            output_base_dir="output"
        )
        
        # 打印结果摘要
        print("\n" + "="*60)
        print("爬取结果摘要：")
        print("="*60)
        
        total_news = 0
        for platform_id, news_dict in results.items():
            platform_name = id_to_name.get(platform_id, platform_id)
            news_count = len(news_dict)
            total_news += news_count
            print(f"✅ {platform_name} ({platform_id}): {news_count} 条新闻")
        
        print(f"\n📊 总计: {len(results)} 个平台成功，{len(failed_ids)} 个平台失败")
        print(f"📊 总新闻数: {total_news} 条")
        
        if failed_ids:
            print(f"\n❌ 失败的平台: {failed_ids}")
        
        print(f"\n💾 数据已保存到: {file_path}")
        print("\n" + "="*60)
        print("爬取完成！")
        print("="*60)
        
    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        print("\n请确保配置文件存在: utils/config.yaml")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

