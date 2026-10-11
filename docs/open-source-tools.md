# 开源工具复用

用户于 2026-10-08 确认：工具性能力可以借鉴 GitHub 开源项目。

优先使用项目现有依赖，通过公开接口复用；复制代码或资源时记录项目、对应版本/提交、修改范围并保留许可证要求的归属。新增库要有实际功能收益与验证。

| 已有工具 | 本项目用途 | 原项目 |
| --- | --- | --- |
| react-markdown | 章节与整本的 Markdown 阅读 | [remarkjs/react-markdown](https://github.com/remarkjs/react-markdown) |
| remark-math、rehype-katex、KaTeX | 数学公式渲染 | [remarkjs/remark-math](https://github.com/remarkjs/remark-math)、[KaTeX/KaTeX](https://github.com/KaTeX/KaTeX) |
| python-pptx | PPTX 文本、表格与对象读取 | [scanny/python-pptx](https://github.com/scanny/python-pptx) |
| python-docx | DOCX 章节、段落与表格读取 | [python-openxml/python-docx](https://github.com/python-openxml/python-docx) |
| pypdf | PDF 读取及原生文字提取 | [py-pdf/pypdf](https://github.com/py-pdf/pypdf) |

本轮继续使用上述现有依赖，没有新增运行时库。适用许可证以锁定版本随包附带的 LICENSE 为准；分发安装包时纳入第三方许可证。文档库可读取格式，不等于复杂公式、扫描页或 OCR 的质量已经验收。

Playwright CLI 仅用于本轮浏览器检查，未添加为产品运行依赖。

为复现真实 React 异步草稿问题，新增开发测试工具：

| 工具（锁定版本） | 用途 | 原项目 / 许可证 |
| --- | --- | --- |
| Vitest 5.0.3 | 与 Vite 配套的组件测试执行器 | [vitest-dev/vitest](https://github.com/vitest-dev/vitest)，MIT |
| React Testing Library 16.3.3 / DOM Testing Library 10.4.2 | 操作真实 React hook 和组件，验证草稿、导航、目录与筛选 | [testing-library/react-testing-library](https://github.com/testing-library/react-testing-library)、[testing-library/dom-testing-library](https://github.com/testing-library/dom-testing-library)，MIT |
| jsdom 30.1.2 | 测试 DOM 环境 | [jsdom/jsdom](https://github.com/jsdom/jsdom)，MIT |

以上均为 devDependencies，版本由 package-lock.json 固定，许可已核对随包元数据；没有复制第三方实现源码。依据 [Vitest 安装说明](https://vitest.dev/guide/) 和 [Testing Library 安装说明](https://testing-library.com/docs/react-testing-library/intro/) 配置；Web 工具链要求 Node.js ≥22.12。
