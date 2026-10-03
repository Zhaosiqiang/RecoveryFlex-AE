# Applied Energy 主实验重设计：distribution BESS repeated-flexibility recovery

日期：2026-10-03

本文件记录已经落地的主实验方案。旧的固定 SOC 序列已被审计并废止；当前研究把恢复政策变成 DSO 可购买的重复本地灵活性合同，并用逐时 AC 约束、未来调用和独立年份验证检验决策价值。当前仍是 development evidence，未达到投稿门槛。

## 1. 建议题目与研究问题

建议题目：

*Network-feasible recovery scheduling for repeated distribution-flexibility services: an AC--SOC benchmark on the IEEE 13-node feeder*

中文工作题目：面向重复配电灵活性合同的网络可行恢复策略：交流潮流审计的电池储能研究。

题目不使用 “first” 或 “novel virtual battery” 等无法证明的表述。研究问题是：

> 当 DSO 采购分布式电池在多个时段重复提供本地灵活性时，把恢复策略本身建模为同时受 SOC、逆变器和不平衡 AC 网络约束的合同对象，是否能在给定供给可靠性的条件下提高可安全承诺功率、减少欠交付，并降低 DSO 的采购成本？

这个问题直接对应 Applied Energy 的 energy storage、smart grid、power-system operation 和 demand-side flexibility scope。贡献必须被写成一个可复现的“决策—物理—验证”链条，而不是一个只改善曲线形状的算法。

## 2. 合同对象和决策层

每个候选灵活性合同由

* c = (P, Ts, Tr, M, epsilon, s_end)

组成：承诺功率 P，服务持续时间 Ts，恢复窗口 Tr，调用序列和周期末端 SOC 下限 s_end。正式开发配置是两个 1 h 服务窗口（区间 8--11、24--27），40 个半小时区间的总 horizon，并在末次服务后保留 12 个半小时区间作为终端恢复机会。P 的 0--300 kW 粗网格用单调性检查加 bisection 精化到小于 0.1 kW；后续稿件只报告这个冻结协议，不把旧的 10 kW 序列结果混入主结果。

### DSO 层的可量化决策

对每条馈线和每个本地灵活性需求 R_f，DSO 在候选合同中选择 x_a，目标为

* 最小化可用性费用、恢复能量费用和失败/未供给惩罚；
* 满足总安全承诺功率 sum(x_a P_a) >= R_f；
* 满足在重复调用样本上的联合 AC、逆变器和 SOC 约束通过概率至少为 1 - epsilon。

费用可先用归一化的容量支付和退化成本，避免凭空创造市场价格；论文报告相对成本、每增加 1 kW 安全承诺的边际成本和 break-even 可用性支付。若必须换算为货币，所有价格在补充材料中给出来源、单位和敏感性范围，不能把任意价格作为结论。

DSO 结果至少包括：安全承诺功率、选择的合同数、调用成功率、欠交付 kW 和 MWh、违反电压/线路/变压器/逆变器约束的小时数、采购成本—可靠性前沿、以及在给定 R_f 下的未供给风险。

### 聚合商层的可量化决策

聚合商对每个合同选择可交付 P 和恢复功率，最大化容量收益减去退化、恢复能量和失败惩罚，同时满足合同可靠性。建议将结果画成 P—可靠性—恢复成本前沿，而不是只报告单个最大值。这样可以回答“何时值得购买更大的合同”以及“网络约束让多少 SOC 能量不可销售”。

## 3. 网络耦合恢复策略

每个服务和恢复时段均运行完整 OpenDSS 不平衡 AC 潮流。约束包括所有相电压、线路和变压器热限、节点相别、电池 SOC 动力学、逆变器 apparent-power limit P^2 + Q^2 <= S^2，以及端点的 SOC 和有功/无功状态。恢复功率是优化变量，不能由一个固定 recovery ratio 直接指定。

建议的实现由两个可复现层组成：

1. 离线阶段按馈线、节点、SOC 区间、时间段和服务动作，用 OpenDSS 生成可行的 transition table。每一条 transition 记录可行/不可行、端点 SOC、P/Q、最小电压裕度、最紧线路或变压器裕度、潮流收敛状态和失败原因。
2. 在线阶段用有限状态动态规划或小型 MILP/MPC 选择恢复动作。目标最大化未来 M 次调用的最小安全承诺功率，减去恢复能量、退化和违反风险。每次动作结束后用 AC 潮流回放，并以端点实测 P/Q 更新 SOC；不允许用表外插值掩盖 AC 失败。

网络状态必须保留相别和空间位置，因此同样的总 SOC 在远端单相、近端三相和变压器受限状态下可以给出不同的可交付功率。论文需要提供 transition-table 哈希或生成参数，补充材料给出状态边界测试和 AC 回放审计。

## 4. 必须比较的基线

所有基线使用相同客户曲线、功率网格、调用序列、可靠性口径、馈线模型和终端边界；变化只来自时序恢复和网络处理。

* B1 SOC-only virtual battery：铜板模型，不运行馈线 AC；把全体电池合成一个能量池。这是能量上限，不应与物理可交付量混写。
* B2 AC-only single-call：当前 SOC 和馈线 AC 可行，但只最大化当前一次服务，采用固定 re-arm 规则，不为未来调用保留头寸。
* B3 myopic AC recovery：恢复动作每一步满足 AC 和 SOC，贪心最大化当前充电或当前可交付量，但不优化 M 次调用的终端 headroom。
* B4 proposed sequence-aware policy：恢复和服务共同服从 AC、SOC 和重复调用合同，显式优化两个服务窗口的最大恒定承诺功率。

B1 提供物理上界，B2 分离 AC 约束的作用，B3 分离网络可行恢复与未来序列价值，B4 才是待检验的完整方法。不要再以“无恢复”或单一固定恢复比例作为唯一对照。

## 5. 数据、馈线与冻结 protocol

现有 2010–2011 数据只能作为开发数据：构建客户分组、调试单位转换、确定状态网格和冻结实现。不能称作 preregistered、untouched test 或最终泛化测试。

独立验证使用现有的 2011–2012 原始文件。先冻结以下内容，再读取该年份的任何结果：客户分组映射、归一化常数、馈线节点和相别、服务/恢复时长、P 网格、epsilon、失败判据、价格参数、随机种子和结果表格式。验证年只复用冻结的映射和协议，不能重新聚类、调阈值、调价格或根据失败案例修改策略。如果 2011–2012 已经被任何选择或调参读取，就改用尚未读取的 2012–2013 数据，并在日志中说明。

当前只把 IEEE 13-node 作为定量主馈线，并在两个相别明确的单相放置点（611.3、634.1）重复审计。IEEE 123-node 的严格基准可行性门失败，且当前 adapter 尚未完成正确的 QSTS 时间推进，因此只能保留为 adapter smoke/diagnostic，不能写成转移验证。开发结果使用十个冻结客户组；统计以日期 × 客户组 × 放置点配对，报告日期聚类 bootstrap 95% CI。

## 6. 主终点与最小可接受结果

主终点是两个服务窗口和独立年份上，基线 AC 可行样本中的平均可行服务功率及 network-LP 相对各基线的配对效应。报告四条方法前沿及日期聚类 95% CI：B1、B2、B3、B4。

次要终点包括：

* 服务交付 MWh、恢复 MWh、被网络限制的恢复功率和端点剩余 SOC；
* 欠交付概率、欠交付量和未供给小时；
* 电压、线路、变压器、逆变器和 SOC 的首要失败原因；
* 在固定 R_f 下的 DSO 采购成本—可靠性 Pareto 曲线；
* 2010–2011 开发到 2011–2012 验证的性能变化和置信区间。

提交 AE 前的硬门槛是：B4 相对 B3 在两个 IEEE 13-node 放置点和独立验证年上都有方向一致且具有实际规模的改善，所有可行调度的 AC replay 通过，失败的 energy-only 反事实被明确标为上界；否则文章保留为 benchmark/方法审计，不宣称有普适决策价值。

## 7. 图表方案

图 1：合同时间线、服务—恢复—再调用过程，以及四种方法如何处理未来 headroom。

图 2：两个 IEEE 13-node 放置点的平均可行服务功率，四条基线同图，独立验证年用分面显示，带日期聚类 95% CI。

图 3：代表性远端单相案例的相电压、线路/变压器负载率、SOC、P/Q 和每次调用端点状态；用阴影标出最紧约束。

图 4：DSO 采购成本—安全承诺功率—失败风险 Pareto 曲线，并给出固定 R_f 的合同选择热图。

图 5：开发年与验证年的性能迁移，按电压、线路、变压器、逆变器和 SOC 分类失败原因。

表 1：数据、馈线、单位和参数冻结清单；表 2：四个基线的决策与约束差异；表 3：两个放置点×独立年份的主终点和 CI；补充材料提供逐时 AC 审计、边界测试和 IEEE 123 diagnostic gate。

绘图必须统一单位、相别颜色、馈线图例和 CI 规则，避免只给单条“代表性曲线”。每张主图都应能直接回答一个 DSO 或聚合商问题。

## 8. 文献定位与不能宣称的内容

Evans、Tindemans 和 Angeli 的 IEEE TSG 2022 工作已经给出聚合储能的 flexibility framework 和 recovery guarantees，因此本文不能宣称“首次 recovery guarantee”或“首次虚拟电池恢复”。Toubeau 等 IEEE TPWRS 2021 已将概率交付保证和样本外市场调度结合；Wanapinit 等 Energy 2022 已研究带调用不确定性和恢复限制的两阶段灵活性采购；Essayeh 等 SEGAN 2025 已研究 DSO 在参与者不确定性下的本地灵活性合同选择；Applied Energy 近年的动态可行域和调度论文也覆盖了 storage-like resource aggregation 与 distribution operation。

本文可合理主张的边界是：把“重复本地灵活性合同的风险校准采购”与“逐次 AC 可行的恢复政策”耦合，并在 IEEE 13-node 的两个放置点上，用冻结协议的独立年份进行外部审计。这个组合的价值要靠 B3 与 B4 的配对结果证明，不能只靠算法名称或一条 SOC 曲线。

建议引用并核对全文：

* Evans, Tindemans, Angeli, IEEE Transactions on Smart Grid 13(5), 3519–3531 (2022), [DOI 10.1109/TSG.2022.3173900](https://doi.org/10.1109/TSG.2022.3173900)。
* Toubeau et al., IEEE Transactions on Power Systems 36 (2021), [DOI 10.1109/TPWRS.2020.3046710](https://doi.org/10.1109/TPWRS.2020.3046710)。
* Wanapinit, Thomsen, Weidlich, Energy 261, 125261 (2022), [DOI 10.1016/j.energy.2022.125261](https://doi.org/10.1016/j.energy.2022.125261)。
* Essayeh, Savelli, Morstyn, Sustainable Energy, Grids and Networks 44, 102061 (2025), [DOI 10.1016/j.segan.2025.102061](https://doi.org/10.1016/j.segan.2025.102061)。
* [Applied Energy scope](https://shop.elsevier.com/journals/applied-energy/0306-2619)。

引用时应使用这些论文的实际结论，不能把“摘要中没有提到 terminal recovery”写成“全文没有 terminal recovery”，也不能把本研究与所有动态可行域工作的差异夸大为“首次 AC-aware flexibility”。

## 9. 实施顺序和停止规则

1. 清理单位和变压器基准，写一页冻结 protocol；记录配置哈希。
2. 在 IEEE 13-node 开发年实现 B1–B4 和逐时 AC replay，先完成状态边界测试。
3. 完成 IEEE 123-node adapter diagnostic gate；基准不可行时只记录失败，不把它升级成量化结论。
4. 冻结代码、配置和绘图脚本；按日期块运行独立年份并合并只读验证目录。
5. 运行 2012–2013 独立验证，生成主表和图；任何故障都记录，不静默丢弃。
6. 以日期 × 客户组 × 放置点做 CI，重复检查端点功率、SOC 增量和失败原因。

停止规则：若 B4 在两馈线或独立年上没有超过 B3 的稳定差异，或差异仅由一个人工阈值造成，停止投稿导向的叙事，保留为内部 benchmark 并回到问题定义。这样可以避免在没有 Applied Energy 决策价值证据时继续堆叠敏感性分析。
