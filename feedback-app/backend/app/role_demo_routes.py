"""Demo view controls inside the existing Google/IAP-authenticated app."""
import uuid

from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from google.cloud import bigquery

from .config import settings
from .demo_context import demo_scope
from .role_demo import COOKIE,controller,decode_view,issue_view,require_action,require_enabled,status


def role_demo_router(repository):
    router=APIRouter()

    def response(data,token=None,clear=False):
        value=JSONResponse(data,headers={'Cache-Control':'private, no-store'})
        secure=settings.demo_frontend_origin.startswith('https://')
        if token:value.set_cookie(COOKIE,token,max_age=1800,httponly=True,secure=secure,samesite='strict',path='/')
        if clear:value.delete_cookie(COOKIE,httponly=True,secure=secure,samesite='strict',path='/')
        return value

    def audit(repo,user,action,selected=None):
        with demo_scope():
            if repo.dataset_ref!=settings.project_id+'.agent_quality_demo':raise HTTPException(503,'Demo audit storage is not isolated')
            repo.workflow_query(f"INSERT INTO `{repo.dataset_ref}.demo_admin_events`(id,admin_id,action,persona_email,created_at) VALUES(@id,@actor,@action,@persona,CURRENT_TIMESTAMP())",[
                bigquery.ScalarQueryParameter('id','STRING',uuid.uuid4().hex),bigquery.ScalarQueryParameter('actor','STRING',user.email),
                bigquery.ScalarQueryParameter('action','STRING',action),bigquery.ScalarQueryParameter('persona','STRING',selected.email if selected else None)])

    @router.get('/api/demo-admin/session')
    def session(request:Request):
        user=controller(request)
        token=request.cookies.get(COOKIE)
        selected=decode_view(user,token,fresh=False)if token else None
        return response(status(user,selected))

    @router.post('/api/demo-admin/persona')
    async def select_persona(request:Request,repo=Depends(repository)):
        require_action(request);user=await run_in_threadpool(controller,request)
        try:
            data=await request.json()
            if not isinstance(data,dict)or set(data)!={'email'}or not isinstance(data['email'],str):raise ValueError()
        except Exception:raise HTTPException(400,'Choose a configured demo view')from None
        token=issue_view(user,data['email']);selected=decode_view(user,token,fresh=False)
        await run_in_threadpool(audit,repo,user,'demo_view_selected',selected)
        return response(status(user,selected),token)

    @router.post('/api/demo-admin/logout')
    def exit_demo(request:Request):
        require_action(request,enabled=False)
        user=request.state.real_user
        from .access_repository import access_repository
        from .auth import _google_user
        access_repository().grant(user.email,refresh=True)
        user=_google_user(user.email,{'name':user.display_name})
        # Exit remains available after the special role is revoked. It never
        # changes the primary IAP identity or application grant.
        return response({'enabled':settings.role_demo_enabled,'active':False,'personas':[],
            'user':None,'realUser':user.public_dict(),'simulatedAi':True},clear=True)

    @router.post('/api/demo-admin/reset')
    async def reset(request:Request,repo=Depends(repository)):
        require_action(request);user=await run_in_threadpool(controller,request)
        token=request.cookies.get(COOKIE)
        if not token:raise HTTPException(401,'Choose a demo view before resetting sample data')
        selected=await run_in_threadpool(decode_view,user,token,fresh=False)
        try:
            if await request.json()!={'confirmation':'RESET DEMO'}:raise ValueError()
        except Exception:raise HTTPException(400,'Explicitly confirm RESET DEMO')from None
        def action():
            from .demo_simulation import reset_demo
            with demo_scope():return reset_demo(repo,user.email)
        result=await run_in_threadpool(action)
        await run_in_threadpool(audit,repo,user,'demo_data_reset',selected)
        if selected:
            token=issue_view(user,selected.email);selected=decode_view(user,token,fresh=False)
        return response({**result,'session':status(user,selected)},token)

    return router
