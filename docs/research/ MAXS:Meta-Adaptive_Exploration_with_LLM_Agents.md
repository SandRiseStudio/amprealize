MAXS: Meta-Adaptive Exploration with LLM Agents
Jian Zhang1, Zhiyuan Wang1, Zhangqi Wang1, Yu He1*, Haoran Luo2
,
Li Yuan4, Lingling Zhang1, Rui Mao2, Qika Lin3∗, Jun Liu1
1Xi’an Jiaotong University 2Nanyang Technological University
3National University of Singapore 4South China University of Technology
zhangjian062422@stu.xjtu.edu.cn, heyucs@stu.xjtu.edu.cn, qikalin@foxmail.com
arXiv:2601.09259v1 [cs.AI] 14 Jan 2026
Abstract
Large Language Model (LLM) Agents exhibit
inherent reasoning abilities through the collabo-
ration of multiple tools. However, during agent
inference, existing methods often suffer from
(i) locally myopic generation, due to the ab-
sence of lookahead, and (ii) trajectory instabil-
ity, where minor early errors can escalate into
divergent reasoning paths. These issues make
it difficult to balance global effectiveness and
computational efficiency. To address these two
issues, we propose meta-adaptive exploration
with LLM agents (MAXS)1, a meta-adaptive
reasoning framework based on LLM Agents
that flexibly integrates tool execution and rea-
soning planning. MAXS employs a lookahead
strategy to extend reasoning paths a few steps
ahead, estimating the advantage value of tool
usage, and combines step consistency variance
and inter-step trend slopes to jointly select sta-
ble, consistent, and high-value reasoning steps.
Additionally, we introduce a trajectory conver-
gence mechanism that controls computational
cost by halting further rollouts once path consis-
tency is achieved, enabling a balance between
resource efficiency and global effectiveness in
multi-tool reasoning. We conduct extensive em-
pirical studies across three base models (MiMo-
VL-7B, Qwen2.5-VL-7B, Qwen2.5-VL-32B)
and five datasets, demonstrating that MAXS
consistently outperforms existing methods in
both performance and inference efficiency. Fur-
ther analysis confirms the effectiveness of our
lookahead strategy and tool usage.
1 Introduction
Large Language Model (LLM) Agents (Huang
et al., 2024) are built on the backbone of LLM,
aiming to leverage tools such as search tools
and code tools to assist in the reasoning pro-
cess. LLM Agents are widely used in complex
Figure 1: An example of LLM Agents solving a task
via multi-step reasoning, dynamically leveraging search
and code tools to obtain the final answer.
*Corresponding authors
1https://github.com/exoskeletonzj/MAXS
problem-solving (Renze and Guven, 2024), medi-
cal question-answering (Yang et al., 2024), search
engines (Nie et al., 2024), and more. Typically,
LLM agents generate queries based on reasoning
requirements and invoke the search tool to obtain
domain-specific knowledge and the latest informa-
tion, and then use it to obtain the corresponding
response (Jin et al., 2025). LLM Agents use the
code tool to generate code based on the reasoning
needs, which is then executed by an interpreter to
return results for precise calculations (Wang et al.,
2024). During the reasoning process, LLM Agents
appropriately call on the search tool and the code
tool to supplement its capabilities and derive the
final result, as shown in Figure 1.
Various strategies are employed during test-
time to improve the efficiency of LLM Agents.
As shown in Figure 2, both Chain of Thought
(CoT) (Wei et al., 2022; Choi et al., 2024) and Tree
of Thought (ToT) (Yao et al., 2023; Haji et al., 2024)
adopt step-by-step reasoning, following prompt-
driven incremental trajectories. In contrast, Monte
Carlo Tree Search (MCTS) (Luo et al., 2025; Gan
et al., 2025) performs global exploration by sim-
ulating whole future paths, where each candidate
step is evaluated by executing it to completion.
These methods face two major issues. The first
1
Figure 2: Comparison of test time reasoning strategies. CoT and ToT follow step by step generation with limited
foresight, while MCTS conducts global simulation at a higher computational cost. On the right, MAXS uses
MiMo-VL-7B-SFT as the backbone and consistently outperforms baseline methods across benchmarks.
is locally myopic generation. Whether using CoT
or ToT, both approaches rely on the existing se-
quence for myopic generation. However, in the
context of Agents, crucial factors such as whether a
tool should be used, whether its use is appropriate,
and whether it brings added value are not reflected
in the decision-making process. The second is-
sue is trajectory instability. Multi-tool reasoning
paths are highly sensitive to early decisions, as
small errors can accumulate and cause divergence.
Tree-based methods like MCTS mitigate this by
simulating multiple futures, but at high cost. As
shown in Figure 4, MCTS often consume approx-
imately one thousand times more tokens to reach
similar performance, due to full-path expansion at
each step.
To address these issues, we propose meta-
adaptive exploration with LLM agents (MAXS), a
meta-adaptive reasoning framework based on LLM
Agents that flexibly integrates tool execution and
reasoning planning. MAXS employs a lookahead
strategy to extend reasoning paths by a few steps,
estimating the potential value of tool usage. It com-
bines step consistency variance and inter-step trend
slopes to jointly select stable, consistent, and high-
value reasoning steps. Additionally, we introduce a
trajectory convergence mechanism to control com-
putational costs and improve inference efficiency
by halting further rollout once path consistency
is achieved. MAXS strikes a balance between re-
source efficiency and global effectiveness within
multi-tool reasoning trajectories.
We conduct extensive empirical studies across
five datasets, including MathVista (Lu et al., 2023),
OlympiadBench (He et al., 2024), EMMA (Hao
et al., 2025), TheoremQA (Chen et al., 2023),
and MATH (Hendrycks et al., 2021), using three
LLM backbones: MiMo-VL-7B (Yue et al., 2025),
Qwen2.5-VL-7B (Xu et al., 2025c), and Qwen2.5-
VL-32B. As shown in the results in Figure 2 and
Table 1, MAXS outperforms existing methods in
both performance and inference efficiency. Ab-
lation studies further validate the effectiveness of
the lookahead strategy and tool usage design. Ad-
ditional experiments confirm the robustness and
adaptability of MAXS with multi-tool reasoning tra-
jectories. The main contributions of this study are
threefold:
•We propose a meta-adaptive agent reasoning
framework, MAXS. To the best of our knowledge,
it is the first method to apply meta-adaptive explo-
ration during the inference-time of LLM Agents.
•A lookahead-based estimation strategy alle-
viates both locally myopic generation and tra-
jectory instability by enabling foresighted, value-
aware tool selection and promoting stable reason-
ing paths.
•Extensive experiments across multiple mod-
els and datasets demonstrate the effectiveness of
MAXS, with ablations and further analyses confirm-
ing the key role of the lookahead strategy and tool
usage design.
2 Methodology
The architecture is illustrated in Figure 3. In this
section, we first introduce the preliminaries of
LLM agents-based reasoning. We then present the
three key components of MAXS: a lookahead strat-
egy for simulating future steps, a value estimation
mechanism for action scoring, and a trajectory con-
2
Figure 3: Illustration of the MAXS framework. Left: LLM Agents generates reasoning steps from input s0 to
final answer sn. Right: At each step, MAXS performs (a) rollout & lookahead, (b) value estimation via advantage
and two variance scores, and (c) integration. A trajectory convergence mechanism halts rollouts early to improve
efficiency.
vergence module that improves inference efficiency
via early rollout termination.
2.1 Preliminaries
Definition 1: Tool-Augmented Reasoning. LLM
Agents reasoning is an iterative process where the
agent generates steps si based on the reasoning his-
tory and input, including the question and prompt
s0:
si ∼πθ(·|s0,s≤i−1), (1)
where πθ is the policy of a pre-trained LLM with
parameters θ, and s≤i denotes all previous reason-
ing steps. In tool-augmented settings, the agent
can choose to invoke external tools (e.g., search or
code) at selected steps Itool ⊆{1,...,T}to en-
hance reasoning. The final output sn is generated
by combining the input question s0 with retrieved
and computed results:
sn ∼πfinal (s0; {di,ri}i∈Itool ). (2)
Definition 2: Test-Time Strategy. To improve
reasoning quality, the agent may apply a selection
policy Qto refine the next step:
ˆ
si ∼Q(·|s0,s≤i−1), (3)
whereˆ
siis the selected optimal step, and Qdenotes
a test-time strategy such as MCTS.
Definition 3: Search Tool Invocation. At rea-
soning step i, the agent may generate a query to
retrieve external knowledge based on input x:
qsearch
i ∼πsearch(s0,si),di = Search(qsearch
i ). (4)
The document di is used to update the next step.
Definition 4: Code Tool Invocation. At some
steps, the agent may also invoke a code tool to
perform computation based on the current state and
input x:
ci ∼πcode(s0,si), ri = Exec(ci). (5)
The result ri is integrated into next reasoning pro-
cess.
2.2 Lookahead Strategy
To mitigate the issue of locally myopic generation,
we adopt lookahead via a rollout process. This
approach evaluates the current step si and future
steps s>i to determine the most optimal decision.
The lookahead process is defined as:
ˆ
si ∼πθ(si |s0,s<i,s>i), (6)
where si is the current reasoning state, s0 repre-
sents the input question and prompt, and s>i in-
cludes future steps to be evaluated.
According to the Bellman Optimality Princi-
ple (Barron and Ishii, 1989), the value of future
steps R(s>i) can be recursively estimated as:
R(s0,s≤i,s>i) = E
K
k=1
γk−1R(si+k) |s ,
(7)
where γis the discount factor for future steps, K
is the maximum number of steps in the lookahead,
3
Methods MathVista OlympiadBench EMMA TheoremQA MATH Avg. Tokens
math physics avg. Math Phys. Chem. avg.
MiMo-VL-7B-SFT
CoT ToT MCTS Guided Decoding ϕ-Decoding 77.20 47.25 30.57 41.57 31.00 33.00 36.00 33.33 46.88 65.67 52.93 2.67 ×107
57.04 6.40 ×1010
73.90 48.51 32.40 43.03 39.00 39.00 40.00 39.33 59.25 69.67 75.30 28.98 21.83 26.55 31.00 22.00 34.00 29.00 40.50 72.67 74.30 22.04 20.87 21.64 32.00 29.00 41.00 34.00 39.12 70.33 74.80 47.86 32.79 42.73 36.00 32.00 41.00 36.33 45.75 73.00 48.80 9.91 ×1010
47.88 1.67 ×108
54.52 7.66 ×108
MAXS (ours) 85.50 52.97 39.74 48.47 47.00 40.00 53.00 46.67 61.00 75.67 63.46 9.86 ×108
Qwen2.5-VL-7B-Instruct
52.00 20.03 9.48 16.44 25.00 19.00 22.00 22.00 31.00 50.00 51.80 19.11 9.52 15.84 33.00 20.00 15.00 22.67 31.00 42.67 CoT ToT MCTS Guided Decoding 49.20 21.32 11.09 17.84 33.00 21.00 19.00 24.33 34.00 50.67 35.21 6.70 ×106
34.29 1.37 ×1010
32.80 4.12 ×1010
35.42 1.46 ×108
44.50 25.46 10.48 20.36 32.00 27.00 16.00 25.00 34.25 53.00 ϕ-Decoding 44.10 26.25 11.05 21.08 20.00 17.00 11.00 16.00 34.75 56.33 34.45 3.17 ×108
MAXS (ours) 56.80 30.49 15.20 25.28 34.00 32.00 30.00 32.33 39.50 60.33 42.85 4.02 ×108
Table 1: Main results across five benchmarks using different decoding methods, grouped by models. For Olympiad-
Bench and EMMA, both overall averages and subset performances are reported. The ‘avg.’ column denotes the
mean accuracy over MathVista, OlympiadBench(avg.), EMMA (avg.), TheoremQA, and MATH.
Math Chemistry Physics Avg.
CoT ToT MCTS Guided Decoding ϕ-Decoding 23.00 33.00 27.00 27.67
25.00 22.00 24.00 23.67
28.00 24.00 19.00 23.67
33.00 30.00 28.00 30.33
31.00 35.00 33.00 33.00
MAXS(ours) 42.00 39.00 37.00 39.33
Table 2: Generalization results on the EMMA dataset
using Qwen2.5-VL-32B-Instruct.
and sis the whole steps. This allows us to incor-
porate future trajectory values into the decision-
making process.
Proposition 1 (Bellman Recursion). The opti-
mal action at step iobeysˆ
si = arg maxsi R(si ∗
γEs>iV∗(s>i) , hence the sequence’s optimum is
obtained by recursively combining current utility
with the future optimal value.
The detailed derivation can be found in Ap-
pendix A.1. Finally, the current step is selected
based on the estimated future values R(s>i) as:
R(s0,s≤i,s>i)
ˆ
si ∼πθ(si |s0,s<i) e
τ
, (8)
where τ controls the diversity of the gener-
ated steps. The complete algorithm and decoding
pipeline are presented in Appendix C.
2.3 Value Estimation
To address trajectory instability, a composite value
function evaluates candidate reasoning trajectories,
incorporating advantage score, step-level variance,
and slope-level variance to promote stable and con-
sistent reasoning.
(1) Advantage Score. We adopt beam search to
maintain K candidate paths. At each decoding
step i, for each path, we perform M independent
stochastic rollouts to simulate possible future tra-
jectories and evaluate the expected lookahead re-
turn (Xu et al., 2025b). Let Fi be the foresight
probability at step iunder the extended rollout:
Fi = πθ(s>i |s0,s≤i), (9)
where s>i denotes the future N steps after i. We
define the global advantage as the relative improve-
ment over the previous step:
Ai = Fi−Fi−1, Radv
i = exp
Ai
τ
, (10)
where τ is a temperature parameter controlling sen-
sitivity. Radv
i reflects the progress gained by choos-
ing si.
(2) Step-Level Variance. Inspired by Lyapunov
stability theory (Shevitz and Paden, 2002), we inter-
pret the lookahead trajectory as a discrete-time dy-
namical system. Let gn denote the log-probability
of the n-th step in the lookahead segment s>i,
and define its mean over a rollout of length N as
¯
1
g=
N
N
n=1 gn, and its variance as:
1
Vstep =
N
(gn−
n=1
¯
g)2
. (11)
N
4
Methods MathVista OlympiadBench EMMA TheoremQA MATH Avg. Tokens
math physics avg. Math Phys. Chem. avg.
MiMo-VL-7B-SFT
MAXS (ours) 85.50 52.97 39.74 48.47 47.00 40.00 53.00 46.67 61.00 75.67 63.46 9.86 ×108
w/o lookahead w/o scorestep w/o scoreslope w/o T.C. 78.20 49.12 30.96 42.94 42.00 36.00 49.00 42.33 58.38 70.67 58.50 2.44 ×108
w/o scoreadv 81.60 51.74 36.68 46.61 43.00 38.00 51.00 44.00 59.25 73.33 60.96 9.88 ×108
82.40 51.15 37.12 46.37 44.00 38.00 51.00 44.33 59.63 74.00 61.35 8.32 ×108
84.10 52.34 38.21 47.53 45.00 38.00 52.00 45.00 60.75 74.67 62.41 8.92 ×108
85.10 52.41 39.04 47.86 47.00 39.00 52.00 46.00 60.88 75.33 63.03 9.95 ×108
Qwen2.5-VL-7B-Instruct
MAXS (ours) 56.80 30.49 15.20 25.28 34.00 32.00 30.00 32.33 39.50 60.33 42.85 4.02 ×108
w/o lookahead 46.30 23.46 10.17 18.94 24.00 23.00 22.00 23.00 28.50 50.33 33.41 1.76 ×108
w/o scoreadv w/o scorestep w/o scoreslope w/o T.C. 48.10 27.96 12.45 22.68 29.00 26.00 25.00 26.67 33.25 54.00 50.40 28.41 12.71 23.07 28.00 26.00 25.00 26.33 33.88 54.67 53.10 28.77 13.14 23.45 29.00 27.00 26.00 27.33 34.75 55.33 55.00 30.19 14.98 25.01 32.00 31.00 29.00 30.67 38.63 58.67 36.94 4.01 ×108
37.67 3.87 ×108
38.79 3.97 ×108
41.60 4.08 ×108
Table 3: Ablation results on different backbones. We individually ablate the lookahead module, three value
estimation scores, and the trajectory convergence (T.C.) mechanism. w/o denotes experiments conducted without
the specified module.
Lower Vstep reflects bounded fluctuation across
future steps, indicating that the trajectory re-
mains stable and resists erratic deviations, akin
to Lyapunov-stable behavior. Accordingly, we
define the step consistency reward as Rstep
i =
exp−
Vstep
τ , where τ is a temperature parameter
controlling sensitivity.
Proposition 2 (Deviation Bound). If Vstep ≤ε,
then |gn−
¯
g|≤√Nεfor every n. Bounding Vstep
therefore constrains state fluctuations and yields
Lyapunov-like stability.
The detailed derivation can be found in Ap-
pendix A.2. This variance serves as a regularizer
to favor smoother forward reasoning paths.
(3) Slope-Level Variance. Inspired by Lipschitz
continuity in mathematical analysis (Heinonen,
2005), we measure the directional smoothness of
the lookahead trajectory by evaluating local slope
variations. We define the first-order difference
δn = gn+1−gn. The average slope over a roll-
out of length N is¯
δ=
1
N−1
N−1
n=1 δn, and its
variance is given by:
1
Vslope=
N−1
N−1
n=1
(δn−
¯
δ)2
. (12)
Lower Vslope implies the trajectory’s local in-
crements are uniformly bounded, resembling
Lipschitz-continuous behavior that avoids abrupt
changes. Accordingly, we define the slope consis-
tency reward as Rslope
i = exp−
Vslope
τ , where τ
controls sensitivity to local oscillations.
Proposition 3 (Lipschitz Bound). If Vslope ≤
ε, then for all m,n we have |gm−gn| ≤
(N−1)ε|m−n|. Hence bounding Vslope lim-
its worst-case jumps and enforces Lipschitz-like
smoothness.
The detailed derivation can be found in Ap-
pendix A.3. This reward encourages the model
to prefer directionally coherent forward reasoning
paths.
Combining Multiple Rewards. We combine the
normalized scores of advantage, consistency, and
slope into a unified reward:
R(s0,s≤i,s>i) = (1−α−β)·Norm(Radv
i )
+ α·Norm(Rstep
i ) + β·Norm(Rslope
i ), (13)
where each component is temperature-scaled
and normalized by Norm(Ri) = exp(Ri/τ)
jexp(Rj/τ) ,
with τ = 0.6.
Replacing this formulation of Rinto Eq. 8, the
objective becomes sampling from the joint distri-
bution that captures advantage, consistency, and
directional smoothness.
2.4 Trajectory Convergence
To reduce computation and improve inference ef-
ficiency, we monitor the variance of candidate
rewards R(s0,s≤i,s>i) at each step. Once the
5
Figure 4: Inference-time scaling law: Accuracy vs. To-
ken usage for different models during decoding.
Figure 5: Accuracy–cost trade-off under varying looka-
head steps across datasets.
variance falls below a threshold δ, we stop roll-
out and resume auto-regressive decoding. Let
Ri = {R(k)(s0,s(k)
≤i,s(k)
>i)}K
k=1. The early stop-
ping condition is:
Var(Ri) ≤δ. (14)
We terminate rollout at step i and resume de-
coding under the auto-regressive process. For
all experiments, we set the convergence threshold
δ= 0.002 to balance efficiency and stability.
3 Experiments
3.1 Experimental Settings
Benchmarks. We evaluate our proposed method,
MAXS, on five diverse and challenging reasoning
benchmarks to assess its performance across both
unimodal and multimodal domains. The selected
datasets are MathVista, OlympiadBench, Theo-
remQA, MATH, and EMMA. More dataset details
can be found in Appendix B.
Backbones and Hyperparameters. We con-
duct experiments using three multimodal language
models: MiMo-VL-7B, Qwen2.5-VL-7B, and
Qwen2.5-VL-32B, to evaluate the robustness and
generalizability of MAXS across different archi-
tectures and model scales. All experiments are
implemented on NVIDIA A800 GPUs with 80GB
VRAM, using the vLLM (Kwon et al., 2023) infer-
ence engine. We keep the decoding configuration
fixed for fair comparison, where K = 1, M = 4, and
N = 4. Under this setting, the maximum step of rea-
soning considered is 13. The step scoring strategy
is controlled by α= 0.3 and β= 0.2, which balance
different components of the score. The top-p value
is set to 0.95 to ensure a good trade-off between
diversity and precision in generation.
Metrics. We adopt the pass@1 (Chen et al.,
2021) rate as our primary accuracy (Acc.) met-
ric to evaluate the correctness of the final generated
answer. To measure computational efficiency, we
also report the average number of input and out-
put tokens consumed by the backbone model for
generating each solution.
Tools. During inference, the LLM agents au-
tonomously invoke external tools to support com-
plex reasoning via code execution and knowledge
retrieval. Specifically, a Python-based Code In-
terpreter executes model-generated code for accu-
rate computations, while a Search Engine retrieves
external knowledge-implemented via an LLM for
convenience.
Baselines. We compare MAXS against five repre-
sentative reasoning methods, including CoT, which
generates a single step by step reasoning chain,
ToT and MCTS, which explore reasoning trees with
pruning via self evaluation or Monte Carlo rollouts,
Guided Decoding (Xie et al., 2023), which uses
stochastic search guided by self evaluation, and
ϕ-Decoding (Xu et al., 2025a), which selects steps
based on simulated foresight and path alignment.
3.2 Main Results
MAXS improves average performance across
backbones. As shown in Table 1, MAXS consis-
tently outperforms five strong baselines, achieving
SOTA results. On MiMo-VL-7B, it reaches 63.46%
accuracy-6.42% higher than ToT. On Qwen2.5-
VL-7B, it surpasses Guided Decoding by 7.43%,
demonstrating strong generalization.
MAXS balances effectiveness and efficiency.
While tree-based methods like ToT and MCTS
6
Figure 6: Radar plot of accuracy under different tool
configurations across datasets.
Figure 7: Accuracy heatmap under different value esti-
mation weights (α, β) across datasets.
are competitive, they require up to 100× more to-
kens. On MiMo-VL-7B, MAXS uses 9.86 ×108
tokens, compared to ToT’s 6.40×1010 and MCTS’s
9.91 ×1010. Compared to efficient methods like
ϕ-Decoding, MAXS achieves notably higher ac-
curacy with minimal additional cost, reflecting its
superior allocation of computation for reasoning.
3.3 Generalization and Scalability
MAXS’s superiority persists when scaling to the
32B model size. We conduct experiments on the
EMMA benchmark using the Qwen2.5-VL-32B
model. As shown in Table 2, MAXS yields even
greater improvements on the larger model, surpass-
ing the strongest baseline, ϕ-Decoding, by 6.33%.
This confirms its ability to capitalize on the ad-
vanced reasoning potential of larger LLMs.
3.4 Inference-Time Scaling
MAXS method demonstrates a superior trade-
off between performance and computational
efficiency. As shown in Figure 4, MAXS con-
sistently occupies the optimal top-left region, de-
livering the highest accuracy for any given token
budget on the MiMo-VL-7B model. Horizontally,
to achieve a comparable accuracy level of 49%,
MAXS requires approximately 1,000 times fewer
tokens than the MCTS baseline. Vertically, with a
similar computational cost to ϕ-Decoding, MAXS
achieves a higher accuracy, showcasing a perfor-
mance advantage of nearly 8%.
4 Analysis
4.1 Ablation Studies
To assess the impact of each component in MAXS,
we perform a systematic ablation study by remov-
ing one module at a time on MiMo-VL-7B and
Qwen2.5-VL-7B. Results in Table 3 reveal the fol-
lowing key insights:
Lookahead is essential for globally-aware rea-
soning. Removing the lookahead module leads to
the steepest performance drop (–4.96% on MiMo-
VL, –9.44% on Qwen2.5-VL), highlighting its role
in simulating future trajectories and escaping local
optima. This aligns with the Bellman principle and
confirms lookahead as fundamental.
Advantage score dominates value estimation.
Among the three reward signals, ablating the advan-
tage score yields the greatest degradation, proving
it is the key driver of effective step selection. In
contrast, step and slope variance mainly aid stabil-
ity, with smaller impacts.
Trajectory convergence improves efficiency with
little cost. Although its removal slightly affects
accuracy, trajectory convergence reduces inference
cost by terminating redundant rollouts, offering
efficiency gains without sacrificing quality.
4.2 Analysis of Lookahead Steps
A 4-step lookahead offers the best balance be-
tween accuracy and efficiency. As shown in Fig-
ure 5, accuracy improves from 3 to 4 steps but
plateaus at 85.3%–85.8% beyond that. Meanwhile,
token usage rises sharply-from 2.05×107 at 4-step
to 3.07 ×107 at 6-step-incurring a 49.8% over-
7
head. This confirms 4-step as the efficiency frontier,
where further gains no longer justify the cost.
4.3 Analysis of Tool Utilization
Code and search are complementary, removing
either harms performance. As shown in Fig-
ure 6, dropping code or search reduces accuracy
from 63.46% (full model) to 60.81% (–2.65%) and
56.36% (–7.1%), respectively. The largest drop
(52.07%, –11.4%) occurs when both are removed,
underscoring their synergy in multi-tool reasoning.
Code is especially critical for symbolic reason-
ing. On MathVista, removing code drops accu-
racy from 85.5% to 73.0% (–14.7%), versus 82.0%
(–4.1%) without search. While search aids infor-
mation access, precise computation from code is
key to correctness in complex tasks.
4.4 Analysis of Value Estimation Weights
Combining step and slope scores (α=0.3, β=0.2)
yields the best overall performance. As shown
in Figure 7, the model achieves peak accuracy
(63.5%) when α=0.3 and β=0.2, validating the
effectiveness of jointly weighting step-based and
slope-based rewards in Equation 13. This config-
uration outperforms the advantage-only baseline
(α=0, β=0, 55.2%) by +8.3%. Moreover, adjacent
settings also yield competitive results, suggesting
that the reward formulation is both robust and well-
balanced.
4.5 Analysis of Reasoning Steps
Most problems are solved within 4–8 steps, val-
idating the 13-step cap. As shown in Figure 8,
most reasoning trajectories conclude between steps
4 and 8 across datasets. OlympiadBench peaks later
at steps 7–8 (23% each), suggesting greater com-
plexity, while MathVista, EMMA, and TheoremQA
concentrate around steps 5–6, covering 58–65% of
cases. Kernel density curves show OlympiadBench
spans a broader range (6–9 steps), whereas others
are more tightly clustered. Reasoning rarely ex-
ceeds 13 steps, justifying our choice of a 13-step
cap. These trends confirm that moderate-length
trajectories suffice for most problems, with deeper
steps reserved for harder cases.
Appendix D provides additional analysis on roll-
out, beam size, value estimation methods and sig-
nificance test, while Appendix E presents success-
ful and failure cases.
Figure 8: Distribution of reasoning steps across datasets.
5 Related Works
LLM Agents and Tool-Augmented Reasoning.
LLM Agents enhance language models by dynam-
ically invoking tools (e.g., search, code) to sup-
port complex reasoning (Renze and Guven, 2024;
Yang et al., 2024; Zhang et al., 2026b,a). Early
approaches insert API calls to improve factual ac-
curacy (Jin et al., 2025; Wang et al., 2024), while re-
cent frameworks integrate planning and tool selec-
tion into multi-step decision-making (Baker et al.,
2019; Torreno et al., 2017; Zhang et al., 2024).
However, most rely on locally greedy decoding
and lack long-term tool utility estimation. We ad-
dress this gap via lookahead-based evaluation and
stability-aware step selection.
Inference-Time Scaling and Optimization.
Inference-time methods like ToT (Yao et al., 2023),
MCTS (Gan et al., 2025), and Best-of-N (Gui
et al., 2024) improve answer quality by explor-
ing multiple paths, but often at high computational
cost. Efficiency-focused approaches introduce sam-
pling strategies (Ma et al., 2025) with early stop-
ping (Chen et al., 2024) or pruning (Xu et al.,
2025a). Our method complements them by combin-
ing lightweight value estimation with convergence-
aware rollouts for efficient multi-tool reasoning.
6 Conclusion
In this work, we propose MAXS, a meta-adaptive
exploration framework that mitigates local myopia
and trajectory instability in LLM agents. MAXS in-
tegrates lookahead rollouts and a composite value
function that incorporates advantage, step variance,
and slope variance to guide stable, efficient de-
cision making. A trajectory convergence mecha-
nism further reduces redundant rollouts. Exper-
iments on five benchmarks and three backbones
demonstrate improved reasoning performance and
reduced cost, with ablations confirming the synergy
between lookahead and value-based guidance.
8
References
Bowen Baker, Ingmar Kanitscheider, Todor Markov,
Yi Wu, Glenn Powell, Bob McGrew, and Igor Mor-
datch. 2019. Emergent tool use from multi-agent
autocurricula. In International conference on learn-
ing representations.
EN Barron and H Ishii. 1989. The bellman equation
for minimizing the maximum cost. Nonlinear Anal.
Theory Methods Applic., 13(9):1067–1090.
Mark Chen, Jerry Tworek, Heewoo Jun, Qiming
Yuan, Henrique Ponde de Oliveira Pinto, Jared Ka-
plan, Harri Edwards, Yuri Burda, Nicholas Joseph,
Greg Brockman, Alex Ray, Raul Puri, Gretchen
Krueger, Michael Petrov, Heidy Khlaaf, Girish Sas-
try, Pamela Mishkin, Brooke Chan, Scott Gray,
Nick Ryder, Mikhail Pavlov, Alethea Power, Lukasz
Kaiser, Mohammad Bavarian, Clemens Winter,
Philippe Tillet, Felipe Petroski Such, Dave Cum-
mings, Matthias Plappert, Fotios Chantzis, Eliza-
beth Barnes, Ariel Herbert-Voss, William Hebgen
Guss, Alex Nichol, Alex Paino, Nikolas Tezak, Jie
Tang, Igor Babuschkin, Suchir Balaji, Shantanu Jain,
William Saunders, Christopher Hesse, Andrew N.
Carr, Jan Leike, Josh Achiam, Vedant Misra, Evan
Morikawa, Alec Radford, Matthew Knight, Miles
Brundage, Mira Murati, Katie Mayer, Peter Welinder,
Bob McGrew, Dario Amodei, Sam McCandlish, Ilya
Sutskever, and Wojciech Zaremba. 2021. Evaluat-
ing large language models trained on code. Preprint,
arXiv:2107.03374.
Wenhu Chen, Ming Yin, Max Ku, Pan Lu, Yixin Wan,
Xueguang Ma, Jianyu Xu, Xinyi Wang, and Tony
Xia. 2023. Theoremqa: A theorem-driven question
answering dataset. arXiv preprint arXiv:2305.12524.
Yanxi Chen, Xuchen Pan, Yaliang Li, Bolin Ding, and
Jingren Zhou. 2024. Ee-llm: Large-scale training and
inference of early-exit large language models with 3d
parallelism. In International Conference on Machine
Learning, pages 7163–7189. PMLR.
Wonje Choi, Woo Kyung Kim, Minjong Yoo, and
Honguk Woo. 2024. Embodied cot distillation from
llm to off-the-shelf agents. In Proceedings of the
41st International Conference on Machine Learning,
pages 8702–8721.
Bingzheng Gan, Yufan Zhao, Tianyi Zhang, Jing Huang,
Li Yusu, Shu Xian Teo, Changwang Zhang, and Wei
Shi. 2025. Master: A multi-agent system with llm
specialized mcts. In Proceedings of the 2025 Confer-
ence of the Nations of the Americas Chapter of the
Association for Computational Linguistics: Human
Language Technologies (Volume 1: Long Papers),
pages 9409–9426.
Lin Gui, Cristina Gârbacea, and Victor Veitch. 2024.
Bonbon alignment for large language models and the
sweetness of best-of-n sampling. Advances in Neural
Information Processing Systems, 37:2851–2885.
Fatemeh Haji, Mazal Bethany, Maryam Tabar, Ja-
son Chiang, Anthony Rios, and Peyman Najafi-
rad. 2024. Improving llm reasoning with multi-
agent tree-of-thought validator agent. arXiv preprint
arXiv:2409.11527.
Yunzhuo Hao, Jiawei Gu, Huichen Will Wang, Linjie Li,
Zhengyuan Yang, Lijuan Wang, and Yu Cheng. 2025.
Can mllms reason in multimodality? emma: An
enhanced multimodal reasoning benchmark. arXiv
preprint arXiv:2501.05444.
Chaoqun He, Renjie Luo, Yuzhuo Bai, Shengding Hu,
Zhen Leng Thai, Junhao Shen, Jinyi Hu, Xu Han,
Yujie Huang, Yuxiang Zhang, et al. 2024. Olympiad-
bench: A challenging benchmark for promoting agi
with olympiad-level bilingual multimodal scientific
problems. arXiv preprint arXiv:2402.14008.
Juha Heinonen. 2005. Lectures on Lipschitz analysis.
100. University of Jyväskylä.
Dan Hendrycks, Collin Burns, Saurav Kadavath, Akul
Arora, Steven Basart, Eric Tang, Dawn Song, and Ja-
cob Steinhardt. 2021. Measuring mathematical prob-
lem solving with the math dataset. arXiv preprint
arXiv:2103.03874.
Xu Huang, Weiwen Liu, Xiaolong Chen, Xingmei
Wang, Hao Wang, Defu Lian, Yasheng Wang, Ruim-
ing Tang, and Enhong Chen. 2024. Understanding
the planning of llm agents: A survey. arXiv preprint
arXiv:2402.02716.
Bowen Jin, Hansi Zeng, Zhenrui Yue, Jinsung Yoon,
Sercan Arik, Dong Wang, Hamed Zamani, and Jiawei
Han. 2025. Search-r1: Training llms to reason and
leverage search engines with reinforcement learning.
arXiv preprint arXiv:2503.09516.
Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying
Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E.
Gonzalez, Hao Zhang, and Ion Stoica. 2023. Ef-
ficient memory management for large language
model serving with pagedattention. Preprint,
arXiv:2309.06180.
Pan Lu, Hritik Bansal, Tony Xia, Jiacheng Liu, Chun-
yuan Li, Hannaneh Hajishirzi, Hao Cheng, Kai-
Wei Chang, Michel Galley, and Jianfeng Gao. 2023.
Mathvista: Evaluating mathematical reasoning of
foundation models in visual contexts. arXiv preprint
arXiv:2310.02255.
Haoran Luo, Yikai Guo, Qika Lin, Xiaobao Wu, Xinyu
Mu, Wenhao Liu, Meina Song, Yifan Zhu, Luu Anh
Tuan, et al. 2025. Kbqa-o1: Agentic knowledge
base question answering with monte carlo tree search.
arXiv preprint arXiv:2501.18922.
Chang Ma, Haiteng Zhao, Junlei Zhang, Junxian He,
and Lingpeng Kong. 2025. Non-myopic generation
of language models for reasoning and planning. In
The Thirteenth International Conference on Learning
Representations.
9
Guangtao Nie, Rong Zhi, Xiaofan Yan, Yufan Du, Xi-
angyang Zhang, Jianwei Chen, Mi Zhou, Hongshen
Chen, Tianhao Li, Ziguang Cheng, et al. 2024. A
hybrid multi-agent conversational recommender sys-
tem with llm and search engine in e-commerce. In
Proceedings of the 18th ACM Conference on Recom-
mender Systems, pages 745–747.
Matthew Renze and Erhan Guven. 2024. Self-reflection
in llm agents: Effects on problem-solving perfor-
mance. arXiv preprint arXiv:2405.06682.
Daniel Shevitz and Brad Paden. 2002. Lyapunov stabil-
ity theory of nonsmooth systems. IEEE Transactions
on automatic control, 39(9):1910–1914.
Alejandro Torreno, Eva Onaindia, Antonín Komenda,
and Michal Štolba. 2017. Cooperative multi-agent
planning: A survey. ACM Computing Surveys
(CSUR), 50(6):1–32.
Xingyao Wang, Yangyi Chen, Lifan Yuan, Yizhe Zhang,
Yunzhu Li, Hao Peng, and Heng Ji. 2024. Executable
code actions elicit better llm agents. In Forty-first
International Conference on Machine Learning.
Jason Wei, Xuezhi Wang, Dale Schuurmans, Maarten
Bosma, Fei Xia, Ed Chi, Quoc V Le, Denny Zhou,
et al. 2022. Chain-of-thought prompting elicits rea-
soning in large language models. Advances in neural
information processing systems, 35:24824–24837.
Yuxi Xie, Kenji Kawaguchi, Yiran Zhao, James Xu
Zhao, Min-Yen Kan, Junxian He, and Michael Xie.
2023. Self-evaluation guided beam search for reason-
ing. In Advances in Neural Information Processing
Systems, volume 36, pages 41618–41650. Curran As-
sociates, Inc.
Fangzhi Xu, Hang Yan, Chang Ma, Haiteng Zhao, Jun
Liu, Qika Lin, and Zhiyong Wu. 2025a. ϕ-decoding:
Adaptive foresight sampling for balanced inference-
time exploration and exploitation. In Proceedings
of the 63rd Annual Meeting of the Association for
Computational Linguistics (Volume 1: Long Papers),
pages 13214–13227, Vienna, Austria. Association
for Computational Linguistics.
Fangzhi Xu, Hang Yan, Chang Ma, Haiteng Zhao,
Qiushi Sun, Kanzhi Cheng, Junxian He, Jun Liu,
and Zhiyong Wu. 2025b. Genius: A generalizable
and purely unsupervised self-training framework for
advanced reasoning. In Proceedings of the 63rd An-
nual Meeting of the Association for Computational
Linguistics (Volume 1: Long Papers), pages 13153–
13167. Association for Computational Linguistics.
Jin Xu, Zhifang Guo, Jinzheng He, Hangrui Hu, Ting
He, Shuai Bai, Keqin Chen, Jialin Wang, Yang Fan,
Kai Dang, et al. 2025c. Qwen2. 5-omni technical
report. arXiv preprint arXiv:2503.20215.
Hang Yang, Hao Chen, Hui Guo, Yineng Chen, Ching-
Sheng Lin, Shu Hu, Jinrong Hu, Xi Wu, and Xin
Wang. 2024. Llm-medqa: Enhancing medical ques-
tion answering through case studies in large language
models. arXiv preprint arXiv:2501.05464.
Shunyu Yao, Dian Yu, Jeffrey Zhao, Izhak Shafran,
Tom Griffiths, Yuan Cao, and Karthik Narasimhan.
2023. Tree of thoughts: Deliberate problem solving
with large language models. Advances in neural
information processing systems, 36:11809–11822.
Zihao Yue, Zhenru Lin, Yifan Song, Weikun Wang,
Shuhuai Ren, Shuhao Gu, Shicheng Li, Peidian Li,
Liang Zhao, Lei Li, et al. 2025. Mimo-vl technical
report. CoRR.
Jian Zhang, Zhangqi Wang, Haiping Zhu, Jun Liu, Qika
Lin, and Erik Cambria. 2026a. Mars: A multi-agent
framework incorporating socratic guidance for auto-
mated prompt optimization. In Proceedings of AAAI.
Jian Zhang, Zhiyuan Wang, Zhangqi Wang, Xinyu
Zhang, Fangzhi Xu, Qika Lin, Rui Mao, Erik Cam-
bria, and Jun Liu. 2026b. Maps: A multi-agent frame-
work based on big seven personality and socratic
guidance for multimodal scientific problem solving.
In Proceedings of AAAI.
Zeyu Zhang, Quanyu Dai, Xiaohe Bo, Chen Ma, Rui Li,
Xu Chen, Jieming Zhu, Zhenhua Dong, and Ji-Rong
Wen. 2024. A survey on the memory mechanism of
large language model based agents. ACM Transac-
tions on Information Systems.
10
A Proof of Proposition
A.1 Proof of Proposition 1: Bellman
Recursion
We aim to prove that the optimal decision at step i
satisfies:
ˆ
si = arg max
si
R(si) + γEs>iV∗(s>i), (15)
where R(si) is the immediate utility, γ ∈(0,1) is a
discount factor, and V∗(s>i) is the expected future
value under the optimal policy.
Step 1: Define global optimal value. Let the to-
tal expected return under the optimal policy starting
from the initial input s0 be:
V∗(s0) = max
s1,...,sT
E
T
t=1
γt−1R(st). (16)
We can rewrite this recursively as:
V∗(s0) = max
s1
[R(s1) + γ·Es2 V∗(s≥2)]. (17)
Step 2: Bellman decomposition at step i. At
an arbitrary step i, given history s0,...,si−1, the
value function is:
V∗(s≤i) = max
s>i
E
K
k=1
γk−1R(si+k) s≤i ,
(18)
which can again be written recursively as:
V∗(s≤i) = max
si+1
R(si+1)
(19)
+ γEs>i+1 V∗(s>i+1).
Step 3: Local decision refinement. Now con-
sider choosing si to maximize the full downstream
return:
ˆ
si = arg max
si
Es>i R(si)
+
K
k=1
(20)
γkR(si+k).
then
Let us define:
Q(si) := R(si) + γ·Es>iV∗(s>i), (21)
ˆ
si = arg max
si
Q(si). (22)
Step 4: Relation to lookahead rollout. In
rollout-based approximation, we generate a set of
candidate continuations {s(k)
>i}M
k=1, then use Monte
Carlo estimate:
Es>iV∗(s>i) ≈
1
M
M
k=1
K
j=1
γj−1R(s(k)
i+j), (23)
which retains consistency with the Bellman optimal
formulation.
Conclusion. Thus, our decision strategy:
ˆ
si = arg max
si
R(si) + γ·Es>iV∗(s>i) (24)
recursively links current utility with foresighted tra-
jectory values, consistent with Bellman’s Principle
of Optimality.
A.2 Proof of Proposition 2: Deviation Bound
We aim to show that if the step-level variance of
a rollout trajectory is bounded by ε, then each in-
dividual log-probability score gn is tightly concen-
trated around its mean¯
g:
Vstep ≤ε ⇒ |gn−
¯
g|≤√Nε, (25)
∀n∈{1,...,N}.
Step 1: Definition of variance. By definition,
the step-level variance of the rollout is:
Vstep =
1
N
N
(gn−
n=1
¯
g)2
. (26)
This measures the dispersion of log-probabilities
across the trajectory.
Step 2: Bounding the ℓ2 norm. Let δn := gn−
¯
g
be the deviation from the mean at step n. Then:
N
n=1
δ2
n
= N·Vstep ≤Nε. (27)
This implies the squared ℓ2 norm of the deviation
vector δ = [δ1,...,δN] is bounded.
Step 3: Derive pointwise bound via inequality.
Using the fact that:
∥δ∥2
=
N
n=1
δ2
n ≥max
n
it follows that for each n:
|gn−
¯
g|= |δn|≤∥δ∥≤√Nε. (29)
δ2
n, (28)
11
Step 4: Alternative probabilistic interpretation.
Suppose the log-probability sequence {gn}arises
from a bounded stochastic process. Then¯
gis the
empirical mean, and by applying Chebyshev’s in-
equality:
P(|gn−
¯
g|≥λ) ≤
Vstep
λ2 ≤
ε
λ2 , (30)
which shows that the deviation from the mean is
highly improbable beyond scale √ε.
Step 5: Connection to discrete Lyapunov sta-
bility. The result implies that the rollout tra-
jectory is uniformly bounded within a √Nε-ball
around the mean, which is a sufficient condition for
bounded-input bounded-state (BIBS) stability in
discrete-time systems. That is, ∀gn, |gn−
¯
g|≤
O(√Nε) ⇒ bounded trajectory.
Conclusion. The variance bound implies that the
trajectory exhibits global uniform boundedness,
which is analogous to Lyapunov stability in dy-
namical systems. This supports the interpretation
that minimizing Vstep leads to smoother and more
predictable reasoning behavior.
A.3 Proof of Proposition 3: Lipschitz Bound
We aim to show that if the slope-level vari-
ance of the log-probability sequence {gn}N
n=1 is
bounded by ε, then for any two positions m,n ∈
{1,...,N}, their cumulative difference is linearly
bounded in |m−n|:
Vslope ≤ε
⇒ |gm−gn|≤ (N−1)ε|m−n|.
(31)
Step 1: Define local slope sequence. Let δn :=
gn+1−gn be the first-order discrete derivative
(slope) between adjacent log-probability values:
δn = gn+1−gn, for n= 1,...,N−1. (32)
Let the average slope be:
¯
δ=
1
N−1
N−1
n=1
Step 2: Define slope-level variance. variance is defined as:
Vslope=
1
N−1
N−1
n=1
This measures the local fluctuation in directional
¯
progress. Let ∆n := δn−
δdenote the deviation
from average slope.
Then,
N−1
n=1
∆2
n = (N−1)·Vslope ≤(N−1)ε. (35)
Step 3: Express global difference via telescoping
Let m<nwithout loss of generality. Then
sum. we have:
gn−gm =
n−1
k=m
¯
δk = (n−m)
δ+
n−1
k=m
∆k. (36)
The first term captures the trend, and the second
term reflects local irregularity.
Step 4: Bound the deviation term. By
2
Cauchy–Schwarz inequality:
n−1
k=m
∆k
≤(n−m)·
n−1
∆2
k (37)
k=m
≤(n−m)·
N−1
∆2
k (38)
k=1
≤(n−m)(N−1)ε. (39)
δn. (33)
The slope
(δn−
¯
δ)2
. (34)
Hence,
n−1
k=m
∆k ≤ (n−m)(N−1)ε. (40)
Step 5: Final bound on log-probability differ-
ence. From Eq. (36), we have:
|gn−gm|≤|n−m||¯
δ|
+ (n−m)(N−1)ε.
(41)
In worst-case or centered-slope settings (e.g.,
¯
δ≈0), the term simplifies to:
|gn−gm|≤ (N−1)ε·|n−m|, (42)
which mimics the discrete Lipschitz condition with
constant (N−1)ε.
Step 6: Discrete Lipschitz analogy. f(x) is Lipschitz continuous if:
A function
|f(x)−f(y)|≤L|x−y|, ∀x,y. (43)
Here, the sequence {gn}exhibits analogous behav-
ior, where the bounded variance on discrete slopes
constrains global oscillation across the trajectory.
12
Dataset Category Size
MathVista Overall 1000
OlympiadBench
OE_TO_maths_zh_CEE 1240
OE_MM_maths_zh_CEE 1910
OE_TO_physics_en_COMP 236
OE_MM_maths_en_COMP 150
OE_MM_physics_en_COMP 456
OE_TO_maths_en_COMP 674
OE_TO_maths_zh_COMP 408
OE_MM_physics_zh_CEE 1483
OE_MM_maths_zh_COMP 56
OE_TO_physics_zh_CEE 115
maths (subset total) 4438
physics (subset total) 2290
Overall 6728
EMMA
Math 100
Physics 100
Chemistry 100
Overall 300
TheoremQA Overall 800
MATH Sampled 300
Table 4: Detailed composition of the five datasets used
in our study: MathVista, OlympiadBench, EMMA, The-
oremQA, and MATH. For OlympiadBench, we present
its fine-grained subsets along with their corresponding
sizes. We also report the total number of problems in
the math- and physics-related subsets, where applicable.
For EMMA, we adopt its MINI version, and for MATH,
we sample 300 problems from the full dataset.
Conclusion. The slope variance Vslope directly
governs the rate of directional fluctuation. Bound-
ing it enforces path regularity, controls local cur-
vature, and promotes globally smooth reasoning
progress. This justifies the slope-consistency re-
ward in our value function as a surrogate for dis-
crete Lipschitz continuity.
B Datasets
As illustrated in Table 4, this study utilizes five
publicly available datasets: MathVista, Olympiad-
Bench, EMMA, TheoremQA, and MATH. These
benchmarks cover a wide range of science prob-
lems and are widely used for evaluating reasoning
abilities of large language models.
MathVista. MathVista is a large-scale scientific
reasoning dataset that spans multiple reasoning
types such as algebraic, geometric, statistical, scien-
tific, numeric commonsense, and logical reasoning,
aiming to assess the comprehensive capabilities of
machine learning models in solving complex scien-
tific problems. The dataset(testmini) contains 1,000
data points covering various issues across multiple
disciplines, designed with varying difficulty lev-
els to help researchers evaluate model reasoning
abilities. The release of MathVista supports inter-
disciplinary scientific research.
OlympiadBench. OlympiadBench consists of
two subdomains, maths and physics, and is specif-
ically designed for Mathematical and Physical
Olympiads, featuring a wide range of challeng-
ing problems to assess models’ performance on
high-level scientific tasks. The dataset contains
two difficulty levels: competition level and col-
lege level, reflecting the diversity and depth of real-
world Olympiad problems. It includes two types
of questions: open-ended questions and theorem-
proof questions. To focus on evaluating genera-
tive mathematical reasoning abilities, we select the
6,728 open-ended(OE) questions for our experi-
ments.
EMMA. EMMA is a multimodal scientific rea-
soning dataset covering three subsets: Math,
Physics, and Chemistry. By integrating mathe-
matical expressions, physical formulas, and chemi-
cal symbols with natural language descriptions, it
focuses on testing models’ abilities in interdisci-
plinary scientific reasoning. This version uses the
EMMA dataset, which contains 100 data points
from each subdomain (mathematics, physics, and
chemistry).
TheoremQA. TheoremQA is a benchmark
dataset designed to evaluate the ability of language
models to perform theorem-based reasoning. It
contains 800 high-quality question-answer pairs
grounded in over 350 unique theorems, covering
fields such as mathematics, physics, electrical en-
gineering, computer science, and finance. The
dataset focuses on assessing whether models can
correctly apply formal theorems to solve advanced
problems, making it a valuable resource for study-
ing scientific reasoning in large language models.
MATH. MATH is a benchmark dataset designed
to evaluate the advanced mathematical reasoning
capabilities of language models. It comprises
12,500 high school competition-level problems
drawn from sources such as AMC, AIME, and
other standardized exams. The dataset spans seven
mathematical domains: Prealgebra, Algebra, Num-
ber Theory, Counting & Probability, Geometry, In-
termediate Algebra, and Precalculus. Each prob-
13
Algorithm 1 MAXS Decoding with Lookahead
and Value Estimation
Input: Input prompt s0
Parameter: Model πθ, beam size K, temperature
τ, threshold δ, rollout size M, lookahead size N
Output: Final reasoning trajectory s =
{s1,...,sT}
1: Initialize t←1, s←{s0}
2: while not end-of-sequence do
3: Sample Kcandidates {s(m)
t }M
m=1 ∼πθ(st |
s<t)
4: for each candidate s(m)
t do
5: Rollout s(m)
>t ∼πθ up to length N
6: Compute foresight F(k)
t = πθ(s(k)
>t |s(k)
≤t)
7: Compute advantage Radv
t , step variance
Rstep
t , slope variance Rslope
t
8: Aggregate reward R(k) via Eq. (13)
9: end for
10: if Var({R(k)}) ≤δthen
11: Break rollout, continue auto-regressive
decoding
12: end if
13: Selectˆ
st ∼softmax(R(k)/τ)
14: Appendˆ
st to s, update t←t+ 1
15: end while
16: return sequence s
Figure 9: Accuracy–cost trade-off under varying rollout
steps across datasets.
Figure 10: Accuracy vs. relative cost under varying
beam sizes (1-beam normalized to 100%).
lem includes a detailed step-by-step solution, final
answer, subject label, and difficulty rating, allow-
ing for fine-grained analysis of model performance
across diverse mathematical topics. We randomly
sampled 300 problems from the MATH dataset,
selecting 60 problems from each difficulty level
(Levels 1 through 5) to ensure an evenly balanced
coverage across difficulty tiers.
C MAXS Decoding Algorithm
We summarize the full decoding process in Al-
gorithm 1. At each step t, the model samples K
candidate actions {s(k)
t }K
k=1 from the policy πθ.
For each candidate, a stochastic rollout generates
future steps s(k)
>t, from which the foresight proba-
bility F(k)
t is estimated.
We compute the composite reward R(k) using ad-
vantage score, step-level variance, and slope-level
variance, combined via Eq. (13). If the reward
variance Var({R(k)}) falls below threshold δ, we
terminate rollout early and resume auto-regressive
decoding. Otherwise, the next stepˆ
st is sampled
according to softmax(R(k)/τ) and appended to the
sequence. This process iterates until an end-of-
sequence token is generated.
D Supplement Analysis
D.1 Analysis of Rollout Steps
Rollout steps beyond 4 incur excessive cost with
no accuracy gain. As shown in Figure 9, accu-
racy on OlympiadBench improves from 0.375 to
0.484 when increasing the rollout steps from 3 to
4, but declines thereafter. Meanwhile, token cost
rises sharply-from 332M at 3-step to 564M at 5-
step and 661M at 6-step. This confirms 4-step as
the efficiency frontier, where further rollout yields
diminishing or even negative returns.
D.2 Analysis of Beam Size
1-beam strikes the best balance between accu-
racy and cost. Figure 10 shows that 1-beam
maintains normalized computational cost at 100%
(leftmost dark blue bars). Increasing to 4-beam
14
Figure 11: Comparison of different value estimation methods across datasets.
dramatically raises costs-by +250% on MathVista,
+195% on TheoremQA, and +180% on EMMA-
while accuracy gains remain marginal (< 1.5%).
On OlympiadBench, accuracy rises by only 0.46%
despite a 210% cost increase. These results confirm
that larger beams yield diminishing returns, with
1-beam offering the most efficient trade-off.
D.3 Comparison of Value Estimation Methods
MAXS consistently outperforms Log-
prob–based value estimation. As shown
in Figure 11, MAXS achieves 5.0–10.3% higher
accuracy across all five reasoning benchmarks,
with the largest gains observed on MathVista and
TheoremQA. This confirms our value estimation
method’s superiority in modeling complex reason-
ing trajectories, especially in symbolic tasks where
log-probability fails to capture structural value.
The stable margin of 5.0–7.3% on OlympiadBench,
EMMA, and MATH further demonstrates MAXS’s
robustness across diverse reasoning formats.
D.4 Significance Test
To determine whether the gains achieved by MAXS
are statistically significant, we perform McNemar’s
test for paired comparisons between MAXS and
each baseline method. Table 5 reports the results on
two backbones, MiMo-VL-7B-SFT and Qwen2.5-
VL-7B-Instruct. Across all comparisons, includ-
ing strong baselines such as ToT and ϕ-Decoding,
MAXS achieves p < 0.001, which is well below
the significance threshold α= 0.05. These results
indicate that the improvements of MAXS over ex-
isting decoding strategies are statistically signifi-
cant and consistent across model architectures.
Comparison p-value Significance
MiMo-VL-7B-SFT
MAXS vs. CoT <0.001 ✓
MAXS vs. ToT <0.001 ✓
MAXS vs. MCTS <0.001 ✓
MAXS vs. Guided Decoding <0.001 ✓
MAXS vs. ϕ-Decoding <0.001 ✓
Qwen2.5-VL-7B-Instruct
MAXS vs. CoT <0.001 ✓
MAXS vs. ToT <0.001 ✓
MAXS vs. MCTS <0.001 ✓
MAXS vs. Guided Decoding <0.001 ✓
MAXS vs. ϕ-Decoding <0.001 ✓
Table 5: Results of McNemar’s Test for Statistical Sig-
nificance. We compare our proposed MAXS method
against all baseline methods across two base models.
A p-value < 0.05 indicates a statistically significant
difference. As shown, MAXS demonstrates significant
improvement over all baselines.
E Case Study
In this section, we present a successful case (Fig-
ure 12) and a failure case (Figure 13), respectively.
E.1 Successful Case
Figure 12 presents an example of problem-solving
using the MAXS method, with the question sourced
from the TheoremQA dataset. As shown in steps
2 and 3, MAXS performs a rollout at each reason-
ing step, exploring multiple candidate reasoning
paths. After generating beam candidates, the model
conducts foresight for each path. Although the fore-
sight depth is set to 4, in later stages of the reason-
ing process, the solution may be completed within
fewer than four steps-thus not every step features
a full four-step foresight chain. Following this,
15
MAXS evaluates each rollout plus foresight chain
using the three advantage metrics proposed in this
paper (Advantage Score, Step-Level Variance, and
Slope-Level Variance) and selects the candidate
with the highest overall score as the action for the
current step. This process continues iteratively un-
til the final solution is reached. Notably, each can-
didate or foresight step may involve different types
of operations such as reasoning, search, or code ex-
ecution. The model dynamically invokes external
tools to ensure high-quality reasoning throughout
the problem-solving process.
E.2 Failure Case
Figure 13 presents a failure case of MAXS on Math-
Vista, illustrating how an early recognition error
can derail multi-step reasoning. The task asks for
the age difference between two individuals shown
in an image. At the initial stage (Meta step 0),
MAXS performs a rollout and generates two beam
candidates. Beam 1 attempts to use the search
tool to identify the individuals, but the returned
results are ambiguous and do not yield a reliable
match, leading to low confidence and a lower eval-
uation score (−0.205). Beam 2 instead relies on
the model’s internal visual recognition. Although
it misidentifies the individuals as Rex Tillerson and
Tânia S ˛agescu, it produces a coherent explanation
and receives a higher score (−0.123). MAXS there-
fore selects Beam 2 and commits to an incorrect
premise.
This initial mistake propagates through later
steps. In Meta steps 1-3, the model retrieves birth
information for the misidentified subjects and per-
forms the arithmetic correctly, but the final answer
is necessarily wrong: it outputs 15 years instead
of the ground-truth 7 years. This case highlights a
limitation of the system: when tool-based retrieval
is uncertain or ineffective, the model may prefer
a more confident but incorrect internal hypothe-
sis, which can dominate the downstream reasoning
process.
16
Figure 12: Successful case of MAXS solving a TheoremQA problem. At each step, it performs rollout and foresight
(up to four steps), evaluates candidates via three advantage metrics, and iteratively selects the best path. The process
dynamically integrates reasoning, search, and tool use.
17
Figure 13: A failure case on the MathVista dataset where MAXS selects an incorrect visual recognition path due to
the low confidence of search tool results. The initial misidentification of the individuals propagates through the
reasoning chain, leading to an erroneous final answer despite valid subsequent calculations.
18
