# 研合成果融合

融合多个来源的成果记录，保留归一化词典、候选证据、人工身份决定和固定发布；来源完整快照会撤回未出现记录。

Python 3.11 标准库与 SQLite 即可运行。数据、时钟和文件均在本地，不需要服务凭据。示例只使用合成记录。

## 运行

在仓库根目录执行：

```sh
python -m researchmesh demo
python -m researchmesh network-demo
python -m researchmesh network-demo --out ./network-out
python -m examples.context
python -m unittest discover -s tests -v
python -m compileall -q researchmesh examples
```

示例使用内存或临时目录，不会改动持久台账。`examples/context.json` 记录一组可重复导入的业务输入，字段与时间口径见 `examples/数据说明.md`。`examples.context` 检查数据并调用现有产品入口；它只展示原有业务数据，不计算分析结论。

`tests` 覆盖现有业务生命周期、非法输入、版本和完整性边界，另有示例导入回归。完整测试和上述演示可在一次短终端会话中执行。

## 机构合作网络分析（researchmesh.network）

在成果身份融合之上，新增纯标准库的网络分析子系统，用来区分**真实合作变化**与**来源覆盖变化**。

- **建图口径**：从选定发布版与年份窗取已融合成果；机构别名经固定词典（带摘要、可检测环）归一化；同一成果的多来源记录只贡献一次。`count` 对每个机构对整计一条边，`fractional` 按 `1/C(k,2)` 分配，单机构成果只留节点贡献。缺机构、超大联合成果、身份冲突进入带成果/记录溯源的排除项，不静默丢弃。
- **精确权重**：所有权重内部为 `fractions.Fraction`，输出同时给分子/分母、分数字符串和仅用于展示的小数，显示舍入不参与任何计算。
- **指标与社区**：节点强度（含合作/单机构拆分）、连通分量，以及实际优化加权无向模块度的确定性 Louvain。分辨率、随机种子、平局规则（候选按编号升序、仅严格增益替换）、停止原因与逐轮模块度全部记录；孤立点和无边图也有确定结果。社区是优化产物，与连通分量分别计算，绝不会把分量直接叫社区。
- **两期比较**：每期同时给全量网络和固定共同来源覆盖网络，新来源接入不会被当成新增合作。社区按共同节点的加权重叠，用匈牙利算法做**全局一对一**匹配，并展示分裂、合并与未匹配部分，不依赖社区编号或贪心配对。
- **变化归因**：边级变化可追到成果新增/撤回、身份合并/拆分、机构修订或时间窗进出；来源与口径类变化明确标注“不得计为组织合作绩效”。
- **可复现**：分析包保存发布摘要、固定词典、全部配置与输入、网络与社区结果及各级摘要；重新加载会用包内输入完整重跑并逐项比对，任何篡改都会在校验中暴露。

`researchmesh/network/demo.py` 用两个稠密团体加一条桥边展示“一个连通分量被优化为两个社区”，并保留新来源增补、身份合并/拆分、机构修订、时间窗进出与三类排除项的对照。核心纯函数位于 `researchmesh/network/`，服务入口挂在 `ResearchMesh().analytics`，对应测试见 `tests/test_network_*.py`。

## 容器

```sh
docker build -t local/researchmesh .
docker run --rm --network none local/researchmesh
docker run --rm --network none local/researchmesh python -m examples.context
```

镜像构建完成后运行和测试不下载文件。持久化使用各自命令的本地路径参数；具体操作及参数可通过 `python -m researchmesh --help` 查询。第三方依赖清单为空。
