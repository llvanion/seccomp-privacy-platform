from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from client.adapters.gateway.http_gateway_adapter import GatewayRequestError
from client.app.bootstrap import build_client_service

_, service = build_client_service()
app = FastAPI(title="Privacy Platform Client WebUI", version="0.1.0")


class AttributionRunPayload(BaseModel):
    job_id: str
    start_ts: int
    end_ts: int
    caller: str
    k: int = 20
    n: int = 5
    value_mode: str = "count"
    out_dir: Optional[str] = None


class SeBuildPayload(BaseModel):
    index_name: str
    records: list[dict[str, Any]]


class SeSearchPayload(BaseModel):
    index_name: str
    keyword: str


class TokenIssuePayload(BaseModel):
    actor: str
    scopes: list[str]
    resource_id: Optional[str] = None
    expire_seconds: Optional[int] = None


class TokenRevokePayload(BaseModel):
    revoked_by: str
    reason: str
    jti: Optional[str] = None
    token: Optional[str] = None


class AuditQueryPayload(BaseModel):
    action: Optional[str] = None
    actor: Optional[str] = None
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)


def _run(callable_fn):
    try:
        return callable_fn()
    except GatewayRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>SecComp 隐私计算与数据安全控制台</title>
  <link rel="icon" href="data:,">
  <!-- 引入 vue -->
  <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
  <!-- 引入 Element Plus -->
  <link rel="stylesheet" href="https://unpkg.com/element-plus/dist/index.css">
  <script src="https://unpkg.com/element-plus"></script>
  <!-- 引入图标库 -->
  <script src="https://unpkg.com/@element-plus/icons-vue"></script>
  <!-- 引入 axios -->
  <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
  <style>
    body { font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', '微软雅黑', Arial, sans-serif; margin: 0; background-color: #f0f2f5; }
    .header { background-color: #1a1a1a; color: white; padding: 0 24px; height: 60px; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
    .header h1 { margin: 0; font-size: 20px; font-weight: 500; letter-spacing: 1px; display: flex; align-items: center; gap: 10px; }
    .status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
    .status-ok { background-color: #67c23a; box-shadow: 0 0 5px #67c23a; }
    .status-err { background-color: #f56c6c; box-shadow: 0 0 5px #f56c6c; }
    .main-container { padding: 24px; max-width: 1200px; margin: 0 auto; }
    .box-card { margin-bottom: 20px; border-radius: 8px; }
    .json-pre { background-color: #282c34; color: #abb2bf; padding: 16px; border-radius: 6px; overflow-x: auto; font-family: Consolas, monospace; font-size: 13.5px; line-height: 1.5; margin: 0; box-shadow: inset 0 0 10px rgba(0,0,0,0.5); }
    .section-title { font-size: 16px; font-weight: bold; margin-bottom: 20px; color: #303133; border-left: 4px solid #409EFF; padding-left: 12px; }
    .el-tabs__item { font-size: 15px; }
    [v-cloak] { display: none; }
  </style>
</head>
<body>
  <div id="app" v-cloak>
    <div class="header">
      <h1>
        <el-icon><Monitor /></el-icon> SecComp 隐私计算与数据安全网关
      </h1>
      <div style="font-size: 14px; display: flex; align-items: center; background: rgba(255,255,255,0.1); padding: 4px 12px; border-radius: 20px;">
         <span class="status-dot" :class="healthStatus ? 'status-ok' : 'status-err'"></span>
         Gateway {{ healthStatus ? 'Online' : 'Offline' }}
      </div>
    </div>
    
    <div class="main-container">
      <el-tabs v-model="activeTab" type="border-card" style="border-radius: 8px; overflow: hidden; box-shadow: 0 2px 12px 0 rgba(0,0,0,0.05);">
        
        <!-- 隐私归因 (PSI) -->
        <el-tab-pane name="psi">
          <template #label>
            <span><el-icon><Connection /></el-icon> 隐私归因计算 (PSI)</span>
          </template>
          <div class="section-title">发起多方安全广告归因任务</div>
          <el-form label-width="130px" :model="psiForm" label-position="left">
             <el-row :gutter="30">
               <el-col :span="8">
                 <el-form-item label="任务追踪标识">
                   <el-input v-model="psiForm.job_id" placeholder="例如: job-001"></el-input>
                 </el-form-item>
               </el-col>
               <el-col :span="8">
                 <el-form-item label="时间窗 (Start)">
                   <el-input v-model.number="psiForm.start_ts" type="number"></el-input>
                 </el-form-item>
               </el-col>
               <el-col :span="8">
                 <el-form-item label="时间窗 (End)">
                   <el-input v-model.number="psiForm.end_ts" type="number"></el-input>
                 </el-form-item>
               </el-col>
             </el-row>
             <el-row :gutter="30">
               <el-col :span="8">
                 <el-form-item label="应用调用方">
                   <el-input v-model="psiForm.caller"></el-input>
                 </el-form-item>
               </el-col>
               <el-col :span="8">
                 <el-form-item label="触点匹配上限 (K)">
                   <el-input-number v-model="psiForm.k" :min="1" :max="100"></el-input-number>
                 </el-form-item>
               </el-col>
               <el-col :span="8">
                 <el-form-item label="转化匹配上限 (N)">
                   <el-input-number v-model="psiForm.n" :min="1" :max="100"></el-input-number>
                 </el-form-item>
               </el-col>
             </el-row>
             <el-form-item>
               <el-button type="primary" :loading="psiLoading" @click="runPsi" size="large">
                 <el-icon><Cpu style="margin-right: 5px" /></el-icon> 下发安全计算任务到沙箱
               </el-button>
             </el-form-item>
          </el-form>
          
          <el-divider v-if="psiResult"></el-divider>
          <div v-if="psiResult">
             <div class="section-title" style="border-left-color: #67C23A;">计算结果返回</div>
             <pre class="json-pre">{{ JSON.stringify(psiResult, null, 2) }}</pre>
          </div>
        </el-tab-pane>

        <!-- 密态检索 (SSE) -->
        <el-tab-pane name="sse">
          <template #label>
            <span><el-icon><Search /></el-icon> 密态检索与求交 (SSE)</span>
          </template>
          <el-row :gutter="24">
            <el-col :span="12">
              <el-card shadow="hover" class="box-card">
                <template #header>
                  <div style="font-weight: bold;">1. 构建加密索引 (Build Index)</div>
                </template>
                <el-form label-width="100px" :model="sseBuildForm" label-position="top">
                  <el-form-item label="目标索引名称">
                    <el-input v-model="sseBuildForm.index_name" placeholder="例如: user_records_secure"></el-input>
                  </el-form-item>
                  <el-form-item label="明文业务数据 (自动本地混淆后发出)">
                    <el-input type="textarea" :rows="6" v-model="sseBuildForm.recordsStr" style="font-family: monospace;"></el-input>
                  </el-form-item>
                  <el-form-item>
                    <el-button type="warning" :loading="sseBuildLoading" @click="runSseBuild" style="width: 100%;">
                      <el-icon><Lock style="margin-right: 5px" /></el-icon> 加密并上传到云端存储
                    </el-button>
                  </el-form-item>
                </el-form>
                <div v-if="sseBuildResult" style="margin-top: 15px;">
                   <pre class="json-pre">{{ JSON.stringify(sseBuildResult, null, 2) }}</pre>
                </div>
              </el-card>
            </el-col>
            <el-col :span="12">
              <el-card shadow="hover" class="box-card">
                <template #header>
                  <div style="font-weight: bold;">2. 执行安全查询 (Generate Trapdoor)</div>
                </template>
                <el-form label-width="100px" :model="sseSearchForm" label-position="top">
                  <el-form-item label="检索目标索引">
                    <el-input v-model="sseSearchForm.index_name" placeholder="需与构建时一致"></el-input>
                  </el-form-item>
                  <el-form-item label="匹配关键字">
                    <el-input v-model="sseSearchForm.keyword" placeholder="系统将生成搜索陷门 (Trapdoor) 避免泄露原词"></el-input>
                  </el-form-item>
                  <el-form-item>
                    <el-button type="success" :loading="sseSearchLoading" @click="runSseSearch" style="width: 100%;">
                      <el-icon><Key style="margin-right: 5px" /></el-icon> 注入陷门发起密文检索
                    </el-button>
                  </el-form-item>
                </el-form>
                <div v-if="sseSearchResult" style="margin-top: 15px;">
                   <pre class="json-pre">{{ JSON.stringify(sseSearchResult, null, 2) }}</pre>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- 凭证与数据访问 -->
        <el-tab-pane name="token">
          <template #label>
            <span><el-icon><Key /></el-icon> 数据授权与凭证网关</span>
          </template>
          <el-row :gutter="24">
            <el-col :span="12">
              <el-card shadow="hover" class="box-card">
                <template #header><div style="font-weight: bold;">网关鉴权: 申请临时短效凭证</div></template>
                <el-form label-width="110px" :model="tokenForm">
                  <el-form-item label="调用方 (Actor)">
                    <el-input v-model="tokenForm.actor"></el-input>
                  </el-form-item>
                  <el-form-item label="所需权限许可">
                    <el-input v-model="tokenForm.scopes" placeholder="逗号分隔，如 orders.read"></el-input>
                  </el-form-item>
                  <el-form-item label="指定关联资源">
                    <el-input v-model="tokenForm.resource_id" placeholder="选填，如 order-xxx"></el-input>
                  </el-form-item>
                  <el-form-item label="有效生命周期">
                    <el-input-number v-model="tokenForm.expire_seconds" :min="60" :max="86400" :step="3600"></el-input-number>
                    <span style="margin-left: 10px; color: #909399; font-size: 13px;">秒</span>
                  </el-form-item>
                  <el-form-item>
                    <el-button type="primary" :loading="tokenLoading" @click="issueToken">向 Auth 服务请求 Token</el-button>
                  </el-form-item>
                </el-form>
                <div v-if="tokenResult" style="margin-top: 15px;">
                   <el-alert v-if="tokenResult.token" type="success" title="Token 已安全签发，已自动填入右侧调试工具" :closable="false" style="margin-bottom:10px"></el-alert>
                   <pre class="json-pre">{{ JSON.stringify(tokenResult, null, 2) }}</pre>
                </div>
              </el-card>
            </el-col>
            <el-col :span="12">
              <el-card shadow="hover" class="box-card">
                <template #header><div style="font-weight: bold;">数据总线: 敏感数据安全提取</div></template>
                <el-form label-width="110px" :model="dataForm" label-position="top">
                  <el-form-item label="目标数据资源标识 (Order ID)">
                    <el-input v-model="dataForm.order_id"></el-input>
                  </el-form-item>
                  <el-form-item label="Authorization 标头 (Bearer Token)">
                    <el-input type="textarea" :rows="5" v-model="dataForm.token" style="font-family: monospace;"></el-input>
                  </el-form-item>
                  <el-form-item>
                    <el-button color="#626aef" :loading="dataLoading" @click="fetchData" style="width: 100%;">
                      <el-icon><Document style="margin-right: 5px" /></el-icon> 穿透网关调取明文
                    </el-button>
                  </el-form-item>
                </el-form>
                <div v-if="dataResult" style="margin-top: 15px;">
                   <pre class="json-pre">{{ JSON.stringify(dataResult, null, 2) }}</pre>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </el-tab-pane>

        <!-- 审计日志 -->
        <el-tab-pane name="audit">
          <template #label>
            <span><el-icon><DataLine /></el-icon> 全链路审计台账查询</span>
          </template>
          <div class="section-title">分布式日志与不可篡改存证追溯</div>
          <el-card shadow="never" style="margin-bottom: 20px;">
            <el-form :inline="true" :model="auditForm">
              <el-form-item label="监控动作 (Action)">
                <el-input v-model="auditForm.action" placeholder="例如 token.issue" clearable></el-input>
              </el-form-item>
              <el-form-item label="溯源主体 (Actor)">
                <el-input v-model="auditForm.actor" placeholder="应用标识" clearable></el-input>
              </el-form-item>
              <el-form-item label="记录条数">
                <el-input-number v-model="auditForm.limit" :min="1" :max="500"></el-input-number>
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="auditLoading" @click="runAuditSearch">
                  <el-icon><Filter style="margin-right: 5px" /></el-icon> 抓取审计记录
                </el-button>
              </el-form-item>
            </el-form>
          </el-card>
          
          <div v-if="auditResult">
             <pre class="json-pre">{{ JSON.stringify(auditResult, null, 2) }}</pre>
          </div>
        </el-tab-pane>

      </el-tabs>
    </div>
  </div>

  <script>
    const { createApp, ref, reactive, onMounted } = Vue;
    const { ElMessage } = ElementPlus;

    const app = createApp({
      setup() {
        const activeTab = ref('psi');
        const healthStatus = ref(true);

        const checkHealth = async () => {
          try {
            const res = await axios.get('/api/health');
            healthStatus.value = res.data && res.data.status === 'ok';
          } catch(e) {
            healthStatus.value = false;
          }
        };

        // PSI Tracker
        const psiForm = reactive({ job_id: 'job-demo-2024', start_ts: 1704067200, end_ts: 1706745600, caller: 'webapp-biz', k: 20, n: 5 });
        const psiLoading = ref(false);
        const psiResult = ref(null);
        const runPsi = async () => {
          psiLoading.value = true;
          try {
            const res = await axios.post('/api/attribution/run', psiForm);
            psiResult.value = res.data;
            ElMessage.success('安全计算任务已触发');
          } catch (e) {
            psiResult.value = e.response?.data || e.message;
            ElMessage.error('网关请求被拒绝或失败');
          }
          psiLoading.value = false;
        };

        // SSE Build
        const sseBuildForm = reactive({ index_name: 'demo_idx', recordsStr: '' });
        const sseBuildLoading = ref(false);
        const sseBuildResult = ref(null);
        const runSseBuild = async () => {
          sseBuildLoading.value = true;
          try {
            let records = JSON.parse(sseBuildForm.recordsStr);
            const res = await axios.post('/api/se/index/build', { index_name: sseBuildForm.index_name, records });
            sseBuildResult.value = res.data;
            ElMessage.success('加密索引投递成功');
          } catch (e) {
            sseBuildResult.value = e.response?.data || e.message;
            ElMessage.error('数据结构异常或网关受阻');
          }
          sseBuildLoading.value = false;
        };

        // SSE Search
        const sseSearchForm = reactive({ index_name: 'demo_idx', keyword: 'alice' });
        const sseSearchLoading = ref(false);
        const sseSearchResult = ref(null);
        const runSseSearch = async () => {
          sseSearchLoading.value = true;
          try {
            const res = await axios.post('/api/se/search', sseSearchForm);
            sseSearchResult.value = res.data;
            ElMessage.success('安全检索请求完毕');
          } catch (e) {
            sseSearchResult.value = e.response?.data || e.message;
            ElMessage.error('查询请求失败');
          }
          sseSearchLoading.value = false;
        };

        // Token
        const tokenForm = reactive({ actor: 'frontend-demo', scopes: 'orders.read', resource_id: 'order-123', expire_seconds: 3600 });
        const tokenLoading = ref(false);
        const tokenResult = ref(null);
        const issueToken = async () => {
          tokenLoading.value = true;
          try {
            const payload = { ...tokenForm, scopes: tokenForm.scopes.split(',') };
            const res = await axios.post('/api/token/issue', payload);
            tokenResult.value = res.data;
            if(res.data && res.data.token) {
              dataForm.token = res.data.token;
            }
            ElMessage.success('凭证签发并同步至剪贴板/变量');
          } catch (e) {
            tokenResult.value = e.response?.data || e.message;
            ElMessage.error('鉴权中心拒绝访问');
          }
          tokenLoading.value = false;
        };

        // Data Acccess
        const dataForm = reactive({ order_id: 'order-123', token: '' });
        const dataLoading = ref(false);
        const dataResult = ref(null);
        const fetchData = async () => {
          dataLoading.value = true;
          try {
            const res = await axios.get(`/api/orders/${dataForm.order_id}/sensitive`, {
              headers: { Authorization: `Bearer ${dataForm.token}` }
            });
            dataResult.value = res.data;
            ElMessage.success('数据穿越成功');
          } catch (e) {
            dataResult.value = e.response?.data || e.message;
            ElMessage.error(e.response?.status === 401 ? '无权限或 Token 过期' : '请求失败');
          }
          dataLoading.value = false;
        };

        // Audit
        const auditForm = reactive({ action: '', actor: '', limit: 10 });
        const auditLoading = ref(false);
        const auditResult = ref(null);
        const runAuditSearch = async () => {
          auditLoading.value = true;
          try {
            // Remove empty fields
            const payload = { limit: auditForm.limit };
            if(auditForm.action) payload.action = auditForm.action;
            if(auditForm.actor) payload.actor = auditForm.actor;
            const res = await axios.post('/api/audit/query', payload);
            auditResult.value = res.data;
            ElMessage.success('区块链凭证与日志加载完毕');
          } catch (e) {
            auditResult.value = e.response?.data || e.message;
            ElMessage.error('审计数据网关错误');
          }
          auditLoading.value = false;
        };

        onMounted(() => {
          checkHealth();
          setInterval(checkHealth, 30000);
          
          sseBuildForm.recordsStr = JSON.stringify([
            {"id":"1", "keyword":"alice"},
            {"id":"2", "keyword":"bob"}
          ], null, 2);
        });

        return {
          activeTab, healthStatus,
          psiForm, psiLoading, psiResult, runPsi,
          sseBuildForm, sseBuildLoading, sseBuildResult, runSseBuild,
          sseSearchForm, sseSearchLoading, sseSearchResult, runSseSearch,
          tokenForm, tokenLoading, tokenResult, issueToken,
          dataForm, dataLoading, dataResult, fetchData,
          auditForm, auditLoading, auditResult, runAuditSearch
        };
      }
    });

    for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
      app.component(key, component)
    }
    app.use(ElementPlus);
    app.mount('#app');
  </script>
</body>
</html>
"""


@app.get("/api/health")
def health() -> dict[str, Any]:
    return _run(lambda: service.health())


@app.post("/api/attribution/run")
def attribution_run(payload: AttributionRunPayload) -> dict[str, Any]:
    return _run(
        lambda: service.attribution_run(
            job_id=payload.job_id,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            caller=payload.caller,
            k=payload.k,
            n=payload.n,
            value_mode=payload.value_mode,
            out_dir=payload.out_dir,
        )
    )


@app.post("/api/se/index/build")
def se_build(payload: SeBuildPayload) -> dict[str, Any]:
    return _run(lambda: service.se_build_index(index_name=payload.index_name, records=payload.records))


@app.post("/api/se/search")
def se_search(payload: SeSearchPayload) -> dict[str, Any]:
    return _run(lambda: service.se_search(index_name=payload.index_name, keyword=payload.keyword))


@app.post("/api/token/issue")
def token_issue(payload: TokenIssuePayload) -> dict[str, Any]:
    return _run(
        lambda: service.token_issue(
            actor=payload.actor,
            scopes=payload.scopes,
            resource_id=payload.resource_id,
            expire_seconds=payload.expire_seconds,
        )
    )


@app.post("/api/token/revoke")
def token_revoke(payload: TokenRevokePayload) -> dict[str, Any]:
    return _run(
        lambda: service.token_revoke(
            revoked_by=payload.revoked_by,
            reason=payload.reason,
            jti=payload.jti,
            token=payload.token,
        )
    )


@app.post("/api/audit/query")
def audit_query(payload: AuditQueryPayload) -> dict[str, Any]:
    return _run(
        lambda: service.audit_query(
            action=payload.action,
            actor=payload.actor,
            start_ts=payload.start_ts,
            end_ts=payload.end_ts,
            limit=payload.limit,
        )
    )


@app.get("/api/orders/{order_id}/sensitive")
def sensitive_read(order_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    return _run(lambda: service.sensitive_read(order_id=order_id, bearer_token=token.strip()))
