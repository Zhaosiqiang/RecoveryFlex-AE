# Applied Energy scope alignment and editorial positioning

**审查日期：** 2026-10-03  
**审查对象：** `RecoveryFlex_AE_2026` 当前开发中的研究（标题、摘要和结果尚未冻结）  
**审查目的：** 以 Applied Energy 的官方 scope 和作者指南为准，降低编辑部初筛和转投风险。本文档只做期刊定位，不代表稿件已经达到投稿或接受标准。

## 1. 官方定位和本研究的切入点

Applied Energy 的官方介绍将以下内容列为核心范围：能源转换与节约、能源资源的优化使用、能源系统分析与优化、可持续和安全高效的能源系统，以及连接研究、开发和实施的应用研究。其主题列表明确包括 **energy networks and Smart Grid、energy storage、flexibility/demand response、power-system planning and operation、optimization and decision-making methods for energy systems problems、data analytics for energy problems** 等，并强调研究必须聚焦能源应用方面。见 [Applied Energy 官方期刊描述](https://shop.elsevier.com/journals/applied-energy/0306-2619)。

当前研究可以落在这个交叉点上，但必须把贡献写成能源系统中的可执行决策：

| Applied Energy 官方主题 | 本研究对应对象 | 投稿时必须展示的证据 |
|---|---|---|
| Energy storage | 分布式 BESS 的 SOC、充电、放电和恢复 | 电池额定值、效率、SOC 边界、端点状态和功率读回 |
| Energy networks and Smart Grid | OpenDSS 不平衡配电馈线 | 逐时电压、线路/变压器热限、相别和潮流可行性 |
| Flexibility and demand response | 多次本地灵活性调用合同 | 服务窗口、恢复窗口、调用次数、端点可靠性和欠交付 |
| Optimization and decision-making | 网络感知恢复调度及 DSO 采购选择 | 与铜板、单次 AC、短视恢复基线的同口径比较；安全承诺功率和风险成本 |
| Data analytics / forecasting models | 实际住宅负荷/光伏曲线和严格时间外推 | 数据来源、时间切分、未参与调参的验证年和按日期/用户组统计 |
| Applied aspects of energy | 供给可靠性与采购/承诺决策 | `P_95`、欠交付、约束失败分类和成本—可靠性前沿，而不只是求解器输出 |

因此，论文的中心句应是：**在配电网物理约束下，恢复策略会改变可安全承诺的重复灵活性功率；本文把这个差异转成 DSO/聚合商可以采用的可靠性和采购决策。** 如果文章只保留 SOC 递推或一次 AC 通过率，它会看起来像电池控制/软件审计，而不是 Applied Energy 的应用能源系统研究。

## 2. 当前题目和贡献边界

工作题目建议保持为：

> **Network-feasible recovery scheduling for repeated distribution-flexibility services: an AC--SOC benchmark on the IEEE 13-node feeder**

这个题目包含网络可行性、重复灵活性和恢复策略三个 scope 关键词，且没有使用 “first”“novel”“guaranteed” 等需要大范围文献证明或严格定理支持的词。当前实验只报告 AC–SOC 审计和服务功率前沿，因此不把 procurement 或成本写进题目。

不得把旧稿 *Auditable repeated-service contracts for distribution-connected batteries: separating feeder limits from persistent recovery state* 作为最终题目。旧标题把 “separating feeder limits” 写成了已证明的结论，而旧实验主要由固定 SOC 递推产生；这正是编辑可以据此判断增量性不足的入口。

可以主张的贡献必须限于结果真正支持的组合：

1. 定义一个包含服务功率、服务/恢复窗口、调用次数、端点 SOC 和失败概率的重复灵活性合同；
2. 用 OpenDSS 逐时生成充放电可行域，再用有限时域调度安排恢复；
3. 用统一的 AC 回放比较铜板能量上界、单次 AC、短视恢复和 sequence-aware recovery；
4. 在独立年份、多个客户组和至少两个电气放置点上报告可行服务功率、失败原因和可靠性风险；IEEE 123 diagnostic gate 失败时不写成转移验证。

“首次提出重复恢复”“首次实现 AC-aware flexibility”或“保证所有未来调用”都不应出现在标题、摘要或 Highlights 中。已有储能恢复、灵活性采购和配电网可行域文献使这类绝对表述很容易被要求补充反例或转投；正文应明确说明本研究是一个可复现的 **network-feasible recovery audit workflow**，并给出与近邻工作的可检验差异。

## 3. 编辑初筛的主要风险

以下是基于官方 scope、作者指南和当前稿件证据的编辑推断，而不是 Applied Energy 对任何具体稿件的公开判定规则。每项都对应一个应在投稿前完成的证据门槛。

### 3.1 看起来像通用优化或算法论文

如果摘要以“提出一个 LP/DP/MPC，并提升可行率”开头，编辑可能把文章归为通用优化方法。方法必须被放在 DSO 采购/聚合商承诺这一能源决策中，先说明合同和实际约束，再说明算法是如何实现该决策。

**门槛：** 主表至少给出安全承诺功率、欠交付风险、服务/恢复能量和采购成本或归一化成本；仅有运行时间和求解精度不够。

### 3.2 只有一次潮流通过，没有网络系统发现

单个 IEEE13 案例、单个站点或一次 AC replay 不能证明网络约束改变了重复服务的决策。尤其当铜板和 AC 结果几乎相同时，文章需要解释为什么仍然属于配电网研究。

**门槛：** 至少有不同电气位置/相别、两个馈线尺度或清楚的转移验证；列出电压、线路、变压器、逆变器和 SOC 的首要失败原因，并报告 AC 相对铜板的功率折减。

### 3.3 结果是设定值的代数重述

固定恢复比例、固定 SOC 余量和复制同一事件会让序列曲线在实验前已经确定。把这类曲线写成“发现的容量规律”会触发 novelty/validity 质疑。

**门槛：** 网络可行恢复应为优化变量；主结果应由 profile、位置、AC transition 和端点约束共同产生，并使用独立验证年。SOC-only 曲线只能作为可解释的上界或负对照。

### 3.4 没有应用结果或决策后果

如果没有说明 DSO 为什么要选择这个合同，编辑会把结果看成工程演示。`P_95` 需要连接到一个动作：买多少 kW、接受多大的风险、少欠交付多少 MWh，或在什么价格下采用更大 reserve。

**门槛：** 固定本地需求时给出合同选择和未供给风险；若使用归一化费用，必须写出费用项、单位和敏感性，不能把任意价格包装成经济结论。

### 3.5 泛化被样本单位或数据切分夸大

单一客户组、同月交错切分、开发年被反复读取，都会削弱“未来泛化”表述。严格时间外推和独立年份必须在方法和结果中一致。

**门槛：** 在摘要中只写实际验证单位；主分析按日期 × 客户组做 cluster/bootstrap；验证年、馈线和参数在查看结果前冻结，并保留失败行而不是静默删除。

### 3.6 标题、摘要和图表用词超过证据

“guaranteed”“optimal”“real-time”“generalizable”“field validated”“cost-effective” 等词分别要求定理、全局最优证明、实时基准、外部泛化、现场数据或完整经济假设。当前研究不应先写这些词再寻找证据。

**门槛：** 所有百分比、功率和风险值都能从冻结 commit、公开数据、配置哈希和审计 CSV 重现；不把开发年结果写成独立验证结果，不把规划模型写成现场示范。

## 4. 摘要的定位和建议结构

Applied Energy 官方作者说明要求摘要简洁、事实性强，独立陈述研究目的、主要结果和结论；摘要应避免不必要的参考文献和未定义缩写。具体要求应在投稿时再次核对 [Applied Energy Guide for Authors](https://www.sciencedirect.com/journal/applied-energy/publish/guide-for-authors)，因为作者指南可能更新。

建议摘要按五句组织：

1. **能源问题：** 配电网中的 BESS 需要在一次合同周期内重复提供本地灵活性，但未来调用所需的恢复 headroom 与网络可行性通常分开处理。
2. **明确缺口：** 现有单次可行功率或 SOC-only 恢复规则不能给出同时满足 AC 约束、端点 SOC 和重复可靠性的安全承诺功率。
3. **方法：** 本研究以公开的负荷/光伏时间序列和不平衡 OpenDSS 馈线生成逐时充放电 transition bounds，并用 sequence-aware 调度优化多个服务窗口。
4. **结果：** 用最终冻结实验的 `P_95`、可靠性、约束失败类型和成本/欠交付数字比较四类基线，并明确开发年和独立验证年的差异。
5. **结论：** 说明网络感知恢复何时改变 DSO 采购决策，以及该方法的边界（抽象 BESS、馈线模型、未包含的退化或市场价格）。

推荐的英文句式骨架如下，方括号必须在最终实验后替换为真实数字，不能原样投稿：

> Repeated local flexibility from distribution-connected batteries is limited by both future state-of-charge headroom and time-varying feeder constraints. We formulate a risk-calibrated contract that couples service power, recovery windows, terminal state of charge and an allowable failure probability, and generate its charging and export bounds with an unbalanced AC feeder model. A sequence-aware linear program is compared with a copper-plate energy bound, a single-call AC policy and a myopic recovery policy using [data/feeder/independent-year design]. At the 95% joint AC–SOC reliability level, the proposed policy delivers [X] kW versus [Y] kW for [baseline], while [failure/cost/shortfall result] remains [value] across [validation design]. The results show when network-aware recovery changes the DSO procurement decision and identify the operating conditions under which a copper-plate offer is unsafe.

只有在这些数字来自完整、冻结、独立验证的实验时，摘要才可以使用 “95% reliability”“across two feeders”等表述。若 B4 与 B3 没有方向一致的改善，摘要应降为“auditable benchmark/protocol”，不能继续写 procurement benefit。

## 5. Highlights 的定位

Elsevier 官方支持页要求 Highlights 提供文章核心发现和区别性，通常为 **3–5 条**，每条最多 **85 个字符（含空格）**，并作为单独的可编辑文件提交；见 [How do I include Highlights with my manuscript?](https://www.elsevier.support/publishing/answer/how-do-i-include-highlights-with-my-manuscript)。Highlights 只写已经被主结果证明的发现，不写研究目的、空泛的宣传语、方法名堆砌或未来工作。

以下是方向正确的候选句，方括号或未经验证的数字须在最终结果冻结后替换/删除：

- **AC-feasible recovery makes repeated BESS service a DSO decision.**
- **Network limits reduce safe offers below the copper-plate bound.**
- **Sequence-aware recovery preserves headroom for future calls.**
- **An independent-year audit quantifies reliability and procurement risk.**

提交前逐条检查字符数、主文结果表和图号是否能支持每句话。若没有真实成本模型，使用 “procurement risk” 可以，但不要写 “reduces cost”；若只有 IEEE13，不要写 “generalizes across feeders”。不要在 Highlights 中使用 “first”“novel”“guaranteed” 或 “real-time”。

## 6. Graphical abstract 的定位

Elsevier 说明 graphical abstract 应以简洁、专业的图形让跨学科读者一眼理解研究主线；它会出现在在线搜索结果、目录和 ScienceDirect 文章页，通常不出现在 PDF 正文。官方建议图形具有清楚的起点和终点，最好按从左到右或从上到下的路径阅读，且需单独上传；见 [Graphical abstract in Elsevier journals](https://www.elsevier.com/en-au/researcher/author/tools-and-resources/graphical-abstract)。期刊专属尺寸、文件格式和 AI/版权政策以最新 Guide for Authors 为准。

推荐构图：

`负荷/光伏时间序列 + BESS 合同` → `OpenDSS 逐时 AC bounds` → `sequence-aware recovery` → `AC replay audit` → `P95 safe offer / reliability–procurement frontier`

图中只保留一个主结论：**future recovery headroom and feeder constraints jointly determine the safe repeated-flexibility offer.** 左侧给出两个服务窗口和一个恢复窗口，中间显示电压/线路瓶颈与 SOC 状态，右侧显示四类基线的安全承诺功率前沿。不要放完整电路图、几十个参数、不可验证的百分比、作者头像或“Applied Energy”字样。颜色应区分服务功率、恢复功率、网络瓶颈和 SOC；所有符号与主文一致；在缩小到网页缩略图后仍能读出“输入—网络—恢复—决策”四步。

旧版作者信息包曾给出约 531 × 1328 像素（高 × 宽）的 graphical abstract 最小尺寸；由于期刊页面会更新，最终上传前应以当前 Guide for Authors 的文件要求复核，不能把旧尺寸当作永久规则。

## 7. 投稿包中的编辑可见项

在最终上传前，按 [Elsevier preparing files for Editorial Manager](https://www.elsevier.support/publishing/answer/how-do-i-prepare-my-files-for-submission-in-editorial-manager) 逐项复核：

- 题目、摘要、关键词、所有图表和交叉引用一致；
- Highlights 单独提供可编辑文件；graphical abstract 单独提供；
- 研究数据/代码的来源、公共仓储名称、数据集标题和直接链接可复核；当前 GitHub 只应写成公开开发仓库，Zenodo DOI 生成后再写 persistent archive；
- competing interests、funding、data/code availability、CRediT 作者贡献和 AI 使用声明与作者确认一致；
- 对应作者姓名、所属机构、邮寄地址和邮箱完整。当前工作目录仍缺正式 affiliation 和 corresponding-author email，不能进入 Editorial Manager；
- 文件名简洁、无作者隐私信息，LaTeX source、PDF、图和补充材料来自同一个冻结 commit；
- 旧的 corrected v1 PDF、旧 Highlights 和旧 graphical abstract 不得混入新投稿包。

这些是形式要求，不能替代科学证据。官方支持页也明确提示期刊指南可能规定文章类型、长度、图表和数据要求，因此在生成最终压缩包后还需再打开 [Applied Energy Guide for Authors](https://www.sciencedirect.com/journal/applied-energy/publish/guide-for-authors) 做一次版本核对。

## 8. 投稿前 scope gate

在允许进入 Editorial Manager 前，内部编辑审查应能对下面每一项给出文件和数字证据：

1. 主结果同时包含 BESS、配电网络、重复灵活性和 DSO/聚合商决策，而不是只包含 SOC 公式或一次潮流；
2. B4 相对 B3 的改善在至少两个电气位置/馈线和独立验证年上方向一致，且不是由一个人为阈值产生；
3. `P_95`、欠交付、失败原因和成本/归一化决策指标已由日期 × 客户组统计，并保留所有失败记录；
4. 题目、摘要、Highlights、graphical abstract、cover letter 使用同一套结果和术语；
5. 所有文献差异、数据来源、OpenDSS 版本/馈线文件、参数哈希和代码运行命令可复核；
6. 两位作者、资金、利益冲突、数据/代码许可和 AI 声明已确认，且没有平行投稿；
7. 完成至少一轮编辑初筛、一轮方法审查和一轮对抗审查后，仍不存在“缺少 applied decision”“网络模型没有改变结论”或“验证年被调参污染”的未解决问题。

目前研究仍处在开发和证据补齐阶段，不能据此声称已经符合投稿、外审或接受条件。只有以上门槛全部满足后，才应把题目、摘要和投稿包冻结。

## Official sources checked

- [Applied Energy — official description and aims/scope](https://shop.elsevier.com/journals/applied-energy/0306-2619)
- [Applied Energy — Guide for Authors entry point](https://www.sciencedirect.com/journal/applied-energy/publish/guide-for-authors)
- [Elsevier Support — Highlights](https://www.elsevier.support/publishing/answer/how-do-i-include-highlights-with-my-manuscript)
- [Elsevier — Graphical abstracts](https://www.elsevier.com/en-au/researcher/author/tools-and-resources/graphical-abstract)
- [Elsevier Support — preparing files for Editorial Manager](https://www.elsevier.support/publishing/answer/how-do-i-prepare-my-files-for-submission-in-editorial-manager)

以上页面于 2026-10-03 检索；若投稿页面显示新的长度、文件、AI、数据或图形要求，以最新期刊指南为准。
