# 修复方法：用 commit-tree 改写提交作者而不丢失 merge 历史

> 事故记录：2026-10-30，答疑页并入 debug-integration 时，修正提交作者身份的过程中
> 重建 merge commit 漏传第二个父，导致远程分支 23 个他人提交从历史中消失。
> 远程 HEAD 最终 `4759ff5`，提交总数恢复 143。

## 一、问题根因

`git commit-tree` 手工重建提交时，**父提交必须逐个 `-p` 传入**。
只传一个父会重建出一个普通提交而不是 merge commit，**祖先链就此断裂**。

本次的具体错误：

```
原 merge commit  59ee8a8 parents: 990e68a 1905d93   ← 两个父
错误重建         5893ad4 parents: 1905d93            ← 只剩一个，debug 侧父链丢失
```

后果：远程分支提交总数 143 → 120，debug 侧的 23 个提交从 `git log` 中消失。
**文件内容没变（tree 相同、`git diff` 为空），所以只看 diff 发现不了问题。**

## 二、正确修复步骤

### 步骤 0：先备份可回退点

```bash
git branch backup/pre-fix <当前HEAD>
```

远程侧的对应回退点就是当前远程 HEAD 的 sha（记下来，步骤 5 要用）。

### 步骤 1：取出原提交的全部父

```bash
git log --format='%p' -1 <原merge提交>     # 输出如 "990e68a 1905d93"
```

**这一步是整件事的关键。** 输出有几个 sha，后面就要传几个 `-p`。
用 `git cat-file -p <commit>` 也能看到完整的 `parent` 行。

### 步骤 2：取出原提交的 tree 与消息

```bash
git rev-parse <原提交>^{tree}              # 文件树，内容完全由它决定
git log --format='%B' -1 <原提交> > /tmp/msg.txt
```

tree 相同即文件内容逐字节相同；message 单独取出以保持不变。

### 步骤 3：用正确身份重建（父逐个传）

```bash
# 单父提交
NEW=$(GIT_AUTHOR_NAME="<name>" GIT_AUTHOR_EMAIL="<email>" \
      GIT_COMMITTER_NAME="<name>" GIT_COMMITTER_EMAIL="<email>" \
      git commit-tree <tree> -p <parent> < /tmp/msg.txt)

# merge commit：有多少个父就传多少个 -p
NEW=$(GIT_AUTHOR_NAME="<name>" GIT_AUTHOR_EMAIL="<email>" \
      GIT_COMMITTER_NAME="<name>" GIT_COMMITTER_EMAIL="<email>" \
      git commit-tree <tree> -p <parent1> -p <parent2> < /tmp/msg.txt)
```

重建链时逐个链接：第 N 个提交的父 = 第 N-1 个新提交。

### 步骤 4：验证（不可跳过）

四项全过才能推：

```bash
# 4.1 提交总数一致 —— 最快的红线
git rev-list --count <原提交>        # 例：143
git rev-list --count <新提交>        # 例：143，必须相等

# 4.2 关键提交仍在链中（逐个确认，别只抽一个）
for c in <关键commit1> <关键commit2> <关键commit3>; do
  git merge-base --is-ancestor $c <新提交> && echo "$c ✓" || echo "$c ✗ 丢失"
done

# 4.3 文件内容一致
git diff <原提交> <新提交> --stat    # 必须为空

# 4.4 提交集合逐条比对 —— 最强证据
diff <(git rev-list <原提交> | sort) <(git rev-list <新提交> | sort)
# 差异应当只有「被重建的那几个提交」的新旧 hash
```

**注意**：4.3 通过 **不代表** 4.1/4.2 通过。内容一致 ≠ 历史一致。
本次事故正是只验了 4.3 就推送。

### 步骤 5：切换并推送

```bash
git reset --hard <新提交>

# 推送前先确认远程没有他人新提交
git fetch origin <branch>
git log --oneline <基点>..origin/<branch>     # 应只有你自己的提交

# 用 --force-with-lease 而不是 --force：
# 带上远程当前 sha，远程若已被别人改动则自动拒绝
git push --force-with-lease=<branch>:<远程旧sha> origin HEAD:<branch>
```

`--force-with-lease=<branch>:<sha>` 显式指定「我期望远程仍是这个 sha」，
比裸 `--force` 安全得多：远程一旦被别人推进，推送直接失败而不是覆盖。

### 步骤 6：推送后再核验一次

```bash
git fetch origin <branch>
git rev-list --count origin/<branch>                 # 提交总数
git log --format='%an' origin/<branch> | sort | uniq -c   # 各作者提交数
```

各作者提交数应与事故前一致。确认无误后再删除 `backup/` 分支。

## 三、避坑清单

| 坑 | 正确做法 |
|---|---|
| 重建 merge commit 漏父 | `git log --format='%p' -1 <commit>` 取出全部父，逐个 `-p` |
| 只验 `git diff` 就推送 | 必须同时验 `rev-list --count` 与 `--is-ancestor` |
| 用裸 `--force` | 用 `--force-with-lease=<branch>:<旧sha>` |
| 不看远程就 force | 先 `fetch` + `log <base>..origin/<branch>` 确认无他人提交 |
| 覆盖身份用 `-c user.name=` | 全局配置本就是本人，直接提交；需指定时用 `--author` 或 `GIT_AUTHOR_*` 环境变量 |
| 删掉备份分支过早 | 远程核验通过后再删 |

## 四、为什么不用其他方式

- **`git rebase -i` + `reword`**：能改作者，但要交互式改每个提交；merge 提交在 rebase
  中会被展平，双父结构丢失 → 同样丢历史，且更隐蔽。
- **`git filter-branch --env-filter`**：能批量改作者且保留 merge 结构，但要重写整个
  区间（143 个提交），慢且容易连带改动无关提交。
- **`git filter-repo`**：效果最好，但本机未安装，且同样需要全区间重写。
- **`git commit-tree`（本次采用）**：只重建需要改的那几个提交，其余 141 个 hash 完全不变，
  影响面最小、可逐条验证。前提是**父必须传全**。
