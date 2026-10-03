# Applied Energy 编辑初筛 / 匿名审稿 Round 1

- 审阅日期：2026-10-03
- 审阅对象：`RecoveryFlex_AE_2026/submission_bundle` 的 corrected v1 候选稿
- 审阅立场：Applied Energy 编辑初筛 + 匿名审稿人
- 当前建议：**暂不投稿**。题目属于 Applied Energy 的主题范围，但以当前证据很可能被编辑部以“增量性不足、应用价值不足、验证规模不足”desk reject 或 transfer。需要先完成下面的 P0 修复，再重新进行一轮完整的科学复核。

## 1. 先给结论

题目涉及储能、配电网、灵活性和需求响应，和 Applied Energy 的 scope 是相符的。期刊官方范围明确包含 Energy storage、Energy networks and Smart Grid、Flexibility/demand response、power-system operation，以及“focus must be on applied aspects of energy”：<https://shop.elsevier.com/journals/applied-energy/0306-2619>。

当前稿件最大的风险不是语言或图表，而是主结果没有证明一个新的能源系统发现。稿件把恢复比例、SOC 初值、能量容量、SOC 保留下限固定之后，reserve-limited 曲线几乎完全由预先写入的 SOC 递推式决定；网络 AC 只作为一次通过/不通过的门槛，而且 repeated-service capacity 的主要变化没有由网络、预测误差、用户群或调度策略产生。换言之，稿件现在展示得最好的是“一个可复现的审计流程”和“一个人为设定的恢复不足算例”，还没有达到 Applied Energy 通常要求的、能够改变系统运行或规划决策的贡献。

如果保留当前研究问题，建议把论文重做为“风险校准的序列可行性合同”：给出一般化的 SOC/恢复上界，证明或计算网络约束如何改变该上界，再用至少两个馈线、多个电池位置/相别、多个实际 profile group 和一个明确的 DSO/聚合商决策展示其价值。只增加文字、再画几张同一条 SOC 曲线，不能解决 desk-reject 风险。

## 2. P0：必须先修复的编辑硬伤

### P0-1. 中心结果是预设算术，不是由实验识别出的新现象

证据：

- `submission_bundle/main.tex:43--47` 预先规定 `rho_rearm=0.5540`、`rho_lim=0.30`；
- `scripts/run_corrected_experiment.py:48--53` 固定 `E=500 kWh`、`SOC_initial=0.80`、`SOC_reserve=0.20`；
- `run_corrected_experiment.py:256--298` 对同一个 held-out event 复制 1--6 次，只改变 SOC 递推；
- `results/corrected_v1/statistical_summary.json` 显示 reserve-limited 的 Q25、median、Q75 在每个 M 上完全相同（140、90、70、50、50、40 kW），而 full-rearm 也是几乎全相同（130--140 kW）。

对于 140 kW，服务 SOC 消耗、恢复 SOC 增益和下一次事件的可用余量都由上述常数直接决定。reserve-limited 的 140→90→70→50→50→40 kW 并不是从 80 个 test days 的网络审计中“发现”的关系，而是每个候选 P 代入同一条能量递推后得到的网格结果。full-rearm 的 (C_M=1) 也已经由代码和控制定义保证。稿件把它称为“physical recovery-state effect”容易被审稿人认为是把已设定的模型性质重新包装成经验发现。

**可执行修复：**

1. 在方法中给出该 SOC-only contract 的闭式上界/可行域，并把它明确称为基线或解析基准。
2. 新的主结果必须显示 AC、时间 profile、位置/相别、逆变器额定值或不确定性会改变序列前沿；至少报告 SOC-only、AC network-only、joint AC–SOC 三条 frontier 以及导致失败的约束分类。
3. 改变恢复比、容量、SOC reserve、事件持续时间、服务起始时刻和 battery placement，报告敏感性与置信区间。若曲线仍由常数递推完全决定，则把主张降为“审计协议/基准”，不要称为新的 repeated-service contract。
4. “pre-registered negative control”只能在确实存在时间戳的预注册记录时使用。当前文件只是 pre-specified protocol，应改为“pre-specified negative control”。

### P0-2. AC 模型与序列主结果没有真正耦合

当前模型将 battery 和 PV 建成单相 `constant-PQ load` surrogate。电池的 SOC 在调用方单独递推，AC replay 只返回一次 feasibility 布尔值。sequence-capacity 循环还缓存同一个事件的 AC 结果（`run_corrected_experiment.py:267--274`），然后重复使用缓存结果做 1--6 次的 SOC 计算。因此，主图中的曲线并没有让连续的 feeder physics、逆变器约束或 profile transition 参与 repeated event；它只是先通过一次 AC，再做多次 SOC 算术。

“three-phase AC feeder replay”容易过度表述。实际注入是一个 611.3 单相 140 kW battery 和一个 675.1 单相 300 kW PV，未建模 inverter kVA/current limit、无功控制、相间不平衡控制、端电压响应下的可交付功率，且控制器被关闭。适配器确实测了 terminal power，这是优点，但不足以证明一个真实 BESS 的 AC–SOC 运行合同。

**可执行修复：**

- 以清楚的 constraint decomposition 作为核心：同一 profile 下分别计算 copper-plate/SOC-only、AC network-only 和 joint capacity，报告每次失败是电压、线路、变压器、逆变器还是 SOC。
- 至少增加 IEEE 123 节点或一个公开低压馈线，并在 source/middle/remote、不同相别放置电池；最好在两个独立 feeder 上保持相同协议。
- 为 battery/PV 指定可核查的 kVA、每相电流、P/Q capability 和充放电效率；恢复时也必须经过同一组 AC/inverter constraints。
- 给出 regulator/capacitor control-mode-off 的理由，并做 control on/off 或电压限值敏感性；否则读者无法知道结果是不是由关闭控制器造成。
- 如果暂时只能做 ideal constant-P surrogate，就把题目和结论改成“feeder-replay audit of an abstract contract”，不要把它写成已验证的 distribution-connected battery operation。

### P0-3. 数据外推和样本单位被夸大

`run_corrected_experiment.py:37` 固定 `GROUP=0`，因此实验实际只使用 10 个固定 group 中的一个 group。稿件称“80 held-out customer-days”，但输出是 80 个日期（每个日期有两个 start），不是 80 个独立客户日，也没有跨 group 的外部检验。10 个 group 只是构建了 profile bank，未全部进入主要结果。

同时，`build_profile_bank_v2.py:10--16,40--57` 在每个自然月内按最早 60%/20%/20% 切分。这样 test 日和 train 日在同一个月份、同一批用户、相邻天气条件中交错出现，不是严格的 forward temporal test；“chronological split”在字面上成立，但不能支撑强的未来泛化表述。主结果的 profile-to-feeder mapping（`main.tex:63--68`）又是任意的 0.40+0.30 和 0.10+0.60 stress embedding，并非测量到的 feeder profile。

**可执行修复：**

- 统一术语：当前结果至少应写成“80 held-out dates from one fixed aggregated profile group, two service starts per date”，不能写 customer-days。
- 主实验使用全部 10 个 group，或把 customer/group 作为真正的外部测试维度；报告按 group、季节和日期聚类的置信区间。
- 增加严格的 forward split（例如前 9 个月 train、后 3 个月 test）或 leave-season-out；若保留 within-month split，必须把它称为 date-holdout，并讨论相邻日相关性。
- 给出 group aggregation 的规模、每个 group 的 kW 统计、feeder native load 和 DER rating 的单位依据；对 embedding 系数做预先注册的范围敏感性，而不是只给一个人工压力映射。
- OPSD 不能只在方法中提及“另一个 loader”。若它是外部验证，就在主结果中执行独立复制；若不是，就从摘要和主文删除，保留在补充材料。

### P0-4. 没有一个可量化的系统决策或能源收益

稿件最终输出 140 kW 和 96.25% event success，但没有说明 DSO/aggregator 会据此作出什么不同决定。没有 bid price、revenue、served energy、curtailment、avoided violation、reserve requirement 或 reliability objective，也没有与一个现有 offer/DOE/recovery bidding baseline 的决策比较。Applied Energy 的 scope 接受 modeling/optimization/decision-making，但编辑会问：这个 140 kW 是否比现有方法更安全、更有价值，或能减少什么能源系统成本？

**可执行修复：**

- 选择一个明确的使用场景：例如 DSO 给聚合商发布 repeated-service offer，要求 (P) 在 M 次调用下达到 95% service reliability；将结果转成可交付电量、违约概率、结算收入或网损/弃光变化。
- 至少比较 single-event DOE、SOC/recovery-only baseline、传统 probabilistic/robust offer 和本文 contract。表格要写清约束、输入信息、目标、输出和失败类型。
- 报告“采用本文 contract 后的决策差异”：例如允许的 bid power 减少多少、可靠交付增加多少、额外 reserve 成本多少。没有这种系统级量化，稿件更像软件验证报告。

### P0-5. 文献定位还不足以支撑“新 contract”

当前 Introduction 只有一个短段落，列出 Evans 2022、Xiao 2025、动态 FOR、DOE、communication reservation 等，但没有系统比较“已有工作已经做了什么、本文具体解决哪个不可替代的缺口”。尤其是：

- Evans et al. 已经提供 aggregated-storage recovery guarantees；
- Wanapinit et al. 已经研究带 recovery constraint 的 flexibility bidding；
- Xiao/Lankeshwara/Cheng/Wang/Karneluti 等 Applied Energy 论文覆盖 security capability、dynamic operating envelope、feasible-region aggregation、communication-dependent SOC reservation 和 repeated DR scheduling；
- SSRN 7356679 已经报告 AC-validated local battery procurement/cost recovery，虽不是同一 repeated-state object，但对“AC-audited battery service/procurement”是近邻；
- `docs/reviews/reference_audit.md` 自己已经指出上述边界，但这些解释没有完整进入正文。

**可执行修复：**

1. 增加一张 literature comparison table，列出 recovery state、terminal SOC/deadline、repeated calls、unbalanced AC、uncertainty/forecast error、market/DSO objective、validation feeder 和 public data。
2. 在正文中把贡献改成一个可检验的组合命题，例如“风险校准的 sequence-feasible offer 在现有 single-event DOE 上加入显式 terminal-state contract，并量化其在 AC feeder 上造成的 bid/reliability trade-off”。不要写成“首次提出 repeated recovery”或“首次考虑 recovery”。
3. 加入 SSRN 7356679 的正式引用，并核对所有 2026 online/volume 状态。AE 2026 的参考文献不是越多越好，关键是对每篇近邻文献给出可复核的差异。
4. 若主贡献只是一个验证 protocol，应坦白定位为 benchmark/protocol paper，并重新评估 Applied Energy 是否是最匹配的主刊。

## 3. 主要技术一致性问题（P1）

1. `main.tex:33--57` 的 SOC 方程只定义了事件级 (s_{k+1})，但 admissible-set 中写 (s_{k,j})；服务和恢复每个 half-hour 的状态递推没有正式定义。应明确 (s_{k,j+1})、终端状态、充放电效率和 power readback 如何进入状态。
2. (mathrm{AC}(P,omega,k)) 没有定义 (omega) 的 load/PV trajectory、service start、recovery ratio、battery location 和 all-phase constraints；应给出完整函数签名或算法框。
3. (Pin{0,10,ldots,300}) kW 使 140 kW 只表示 10 kW 网格上的最大值。应报告网格上/下界、细化网格敏感性（例如 1 kW），并避免把 grid artifact 当成精确容量。
4. full-rearm 只对同一 held-out event 的复制进行序列测试，而非实际按日期连续的 multiple calls。应把名称改成“identical-event repeated-call control”，或者另加真实 chronological call sequence。
5. full-rearm 曲线的 130--140 kW 范围来自不同 test-day 的单次 AC 结果；reserve-limited 曲线完全由 SOC grid arithmetic 产生，图 2 的阴影解释需要改成“AC range for full re-arm versus deterministic SOC grid for reserve-limited”，否则会让人误以为两者都来自同样的 profile variation。
6. Fig. 3 的右图点高度集中在 1.00--1.05 pu；失败事件在 AC 适配器返回 NaN 或单个越限值时如何绘制，需要在图注和补充表中列出失败原因。当前 caption 写“retains both accepted and rejected”但可视化没有失败分类。
7. “maximum held-out phase voltage is 1.0506 pu”是一个越过 1.05 的 rejected case。结果应报告 accepted-only extrema 与 all-test extrema 分开，避免读者误解为通过了 1.0506。
8. 300 kW 单相 PV 与 140 kW 单相 battery 的 kV/kVA 额定依据未给出。即使是 stress embedding，也必须说明为什么这种 rating 在 IEEE-13 相别上可接受，并做额定值敏感性。
9. 关闭 OpenDSS controls、使用固定 0.95--1.05 pu、line ratio 1.0 都是重要实验选择，当前没有 control-on 或限值敏感性；至少应作为 supplementary robustness。
10. 统计摘要只有 success-rate 的 day bootstrap；C_M 没有 bootstrap CI，也没有按 group/day/season 的独立单位。reserve-limited 的 Q25=median=Q75 不是“稳定的经验结果”，而是确定性递推，需要如实说明。
11. 论文中称“all generated tables and figures with source code”，但主文没有一张结果表，也没有 failure taxonomy/constraint-attribution 表。建议至少新增：数据/划分表、模型与额定值表、baseline comparison 表、failure cause 表。
12. 参考文献中 `OpenDSS13` 使用 SourceForge 项目页，建议改用 EPRI/OpenDSS 的官方示例或可追溯版本/commit，并在 data/code availability 中写出 feeder 文件 hash。

## 4. 图表和投稿包

现有图形清晰、分辨率和配色合格，但科学信息还不够：

- Fig. 2 的红色曲线几乎是事先给定的 SOC-only staircase，不能作为主图；需要加入 AC/SOC/copper-plate 分解、不同位置/相别和置信区间。
- Fig. 3 左侧三根柱状图重复呈现一个 95% threshold 选择，右侧散点没有显示线路瓶颈、相别或失败原因；应换成“bid power versus success/reliability frontier”和“constraint attribution”。
- Fig. 4 是固定 140 kW 的示意性递推，没有用 test profile 或真实 readback 形成统计结果；应在补充材料中作为机制图，主文留给可泛化结果。
- Fig. 5 只展示一个 group 的一天，应至少展示 group/season 的分布和 train/cal/test 的严格时间边界。
- 投稿包中有 `submission_bundle/NOT_READY.txt`，但它同时写“corrected v1 submission candidate is generated”并写“verified public repository”。GitHub 仓库目前可访问，但本地还有未提交的 `scripts/run_corrected_experiment.py` 修改和 `results/pv500_smoke/` 未跟踪目录；必须冻结一个 commit、重新运行全套实验、重新生成 source ZIP/SHA256 和 PDF。
- 目前没有 DOI。GitHub URL 可用于初审，但建议在最终上传前用 Zenodo 绑定最终 commit；在 DOI 产生前不要在文章中写“persistent DOI archive”像已经存在一样。
- 作者 affiliations、corresponding author、邮箱和作者声明仍待填；这些是行政缺项，不能留到上传页面临时手填后忘记同步 PDF。
- 当前 `main.tex` 的 AI declaration 与用户已授权的声明一致，但应确认 Manus 的正式产品名称和期刊当前 AI policy 的措辞。

## 5. 推荐的新题目和贡献边界

当前题目：

> Auditable repeated-service contracts for distribution-connected batteries: separating feeder limits from persistent recovery state

它把“separating feeder limits”写进标题，却没有实验把 feeder-limited 和 SOC-limited frontier 分开验证，容易被审稿人抓住。建议先完成 P0 后再定标题。可选方向：

- **优先（需要增加多馈线、constraint decomposition、风险校准和决策量化）：**  
  *Risk-calibrated sequence-feasible battery flexibility under unbalanced distribution-feeder constraints*
- **若强调方法接口而不声称新市场模型：**  
  *From event-level flexibility to sequence-feasible distribution services: an AC–SOC audit for batteries*
- **若只能保留当前窄实验（但 AE 风险较高）：**  
  *An auditable protocol for repeated-service battery offers under distribution-feeder constraints*

我不建议继续使用“first/novel repeated-service contract”作为标题或 highlights；更稳妥的创新句式是“we make the terminal-state and repeated-call reliability contract explicit, then quantify the AC/network penalty relative to an SOC-only baseline”。

## 6. 重新进入投稿前的门槛

在下一轮编辑审查前，必须能在一页内部回答：

1. 与 Evans recovery framework、Wanapinit bidding、AE dynamic-FOR/DOE/SRC 以及 AC flexibility-area 工作相比，本文新增的数学对象或决策结果是什么？
2. 若把 OpenDSS 换成铜板系统，主结论是否仍完全相同？若相同，为什么这仍然是配电网论文？
3. 140 kW 和 96.25% 是否对另一个 feeder、battery location、profile group、season 和严格未来日期仍成立？如果不成立，本文报告的是怎样的风险校准方法？
4. 该方法让 DSO/aggregator 的哪个 bid、reserve、settlement 或 reliability 决策发生了可量化变化？
5. 所有数字能否从冻结 commit、公开数据、manifest 和一条命令重现，并且 test split 没有参与任何参数选择？

在这些问题没有得到证据支持前，本稿不应上传 Editorial Manager。当前最合理的结论是“scope 合适、科学证据尚不足”，不是简单润色或补 cover letter。
