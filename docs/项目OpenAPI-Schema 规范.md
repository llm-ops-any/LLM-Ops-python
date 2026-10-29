在 LLMOps 项目中，如果使用完整的 OpenAPI-Schema 规范来描述 API 工具会显得特别繁琐，所以我们对 OpenAPI-Schema 规范进行相应的简化 + 调整，做出如下约定：

1. 所有的外部 API 请求类型只有 GET 和 POST，并没有 DELETE/PUT 等方法，一个路径下可以拥有多个方法，例如同时拥有 GET 和 POST，在项目中使用 OperationId 进行唯一标识判断；
2. 基础的 API 地址有且只有一个，被添加到 server 中，该规范是 LLMOps 项目自行约定的，并不是 OpenAPI 规范；
3. 接口的数据可以作为参数被附加到 Header/Query/Cookie/Path/RequestBody 这 4 个位置；
4. 所有的参数都使用 parameters 进行记录，in 参数的类型支持 path/query/header/cookie/request_body 中，分别代表 请求路径、查询 query、header 请求头、cookie、RequestBody (只有 POST 才有)。
5. type 类型支持 str (字符串)、float (浮点型)、int (整形)、bool (布尔值) 共计 4 种基础类型，注意下该规范并不是 OpenAPI 内置的定义，而是我们为了简化描述方案而约定的。
6. required 字段可选可不选，默认情况下都是 true 代表是必填的。

最基础的完整数据结构如下：

```js
{
	"servers": [{
		"url": "https://weather.example.com"
	}],
	"paths": {
		"/location": {
			"get": {
				"description": "获取特定位置的天气预报信息",
				"operationId": "GetCurrentWeather",
				"parameters": [{
					"name": "location",
					"in": "query",
					"description": "需要获取天气预报的城市名",
					"required": true,
					"schema": {
						"type": "string"
					}
				}],
			}
		},
        "/ip": {
            "post": {
                "description": "根据传递的ip地址获取所在地",
                "operationId": "GetIpLocation",
                "parameters": [{
                    "name": "ip",
                    "in": "query",
                    "description": "需要查询地址的标准ip，例如201.142.15.5",
                    "required": true,
                    "schema": {
                        "type": "string"
                    }
                }]
            }
        }
	}
}
```