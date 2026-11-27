# 项目配置

首次启动会使用程序内置的默认设置。[settings.example.json](settings.example.json) 列出了默认值，可用于查看主图、详情图和 SKU 图的尺寸与文件大小限制，以及服务端口、字体、采集和 AI 设置。

在工具的「设置」中保存后，项目会把设置写入本机的 `config/settings.json`。也可以将示例复制为 `config/settings.json` 后按需修改。程序会将本机设置与默认值合并，省略的字段沿用默认值。

`config/settings.json` 由 Git 忽略。1688 Cookie 和 AI API Key 在本机填写，仓库示例中的对应字段留空。
