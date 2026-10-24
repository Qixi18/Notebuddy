# 主干重绘，保留既有枝条

## 最终范围

用户要求枝条和上一版一致。本轮仅重画下方主干与根部，放弃最初生成的完整树枝稿。原一、二、三本笔记本的枝条 recipe、叶片位置、藤蔓锚点及笔记本/知识点点击入口保持原样。

- 新素材：`apps/web/public/assets/forest/rootstocks-v2.png`，1999×787，RGBA 透明背景。
- 生成方式：内置 `image_gen`，以上一版 `trunks-atlas.webp` 为风格参考；保留生成原文件，复制最终选定稿至项目。
- 接缝处理：从原主枝起点向下补画连接段，终点、切线、半径与原主枝精确对应；新的短主干覆盖下段连接，上沿渐隐。未移动既有冠层。
- 空课程仍沿用原幼树展示，避免更改未请求的空状态。
- 未修改业务数据，未提交或推送 GitHub。

## 验证

- 新增几何回归：一、二、三本笔记本和全部三种 variant 的连接终点、切线、半径及冠层不可变检查。
- 展开后的接头对 stock 起点做逆变换，既有枝条缩放保持原样。复核 17 本远本显露、单本 200 叶全部 pins 场景后，全部接头仍从世界坐标 `(-8,-165)` 开始，不会延伸到树根下方。
- 实际首页、真实 AI 笔记目录的三种树形对照已检查并保存截图。
- 前端全量测试：33 项导航、186 项界面检查通过，总计 219 项。生产构建通过，`git diff --check` 无空白错误。

## 最终生成提示词

```text
Use case: precise-object-edit. Create ONE clean production sprite atlas for NoteBuddy from the reference, on a truly transparent alpha background. IMPORTANT: redraw ONLY THE LOWER TREE TRUNKS AND ROOTS, NOT THE BRANCHES. The app already has its main branches and crown and those must remain exactly unchanged. Discard the long pointed dead stumps of the reference and create three modest, live, gently curving LOWER ROOTSTOCKS, evenly spaced in three separate non-overlapping columns on one wide landscape image. Each rootstock has a grounded, interwoven root flare at the bottom; a short solid living trunk rising from it, with pale grey-brown finely detailed bark and a little delicate olive moss; and a narrow smoothly tapering UPPER NECK centered directly above its roots, so existing app branches can be attached above it. The upper neck ends in a smooth narrow taper, never a jagged broken stump or a flat saw cut. NO CROWN, NO BRANCHES, NO FORKS, NO TWIGS, NO LARGE SIDE PROTRUSIONS. Do not draw any upper tree structure. Short compact lower trunks only, with a shallow natural S bend, not twisted, not corkscrewing, no exaggerated curves. Their centerlines stay close to vertical. Keep the original botanical watercolor realism, soft organic edges, restrained warm bark highlights and subtle moss at roots. Same height, same scale and same root baseline in all three columns, slight natural differences among the three lower trunks only. Root width about twice upper-trunk width at its base. Fine grass and small stones only immediately among the roots, never a horizontal ground band. Very clean separated silhouettes and ample transparent margins around every rootstock. NO background, NO scenery, NO colored glows, NO checkerboard, NO text, NO labels, NO borders, NO watermark. One landscape transparent PNG atlas. Again: ONLY THREE SHORT LOWER TRUNKS WITH ROOTS, ZERO BRANCHES. The existing thin branches are already implemented separately and must not be redesigned.
```
