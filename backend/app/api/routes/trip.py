"""旅行规划 API 路由 (LangGraph 工作流驱动)"""

from fastapi import APIRouter, HTTPException, status
from loguru import logger
from ...models.schemas import (
    TripRequest,
    TripPlanResponse,
    ErrorResponse,
)
from ...workflow import run_trip_planner_workflow, get_trip_planner_graph

router = APIRouter(prefix="/trip", tags=["旅行规划"])


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    summary="生成旅行计划",
    description="根据用户输入的旅行需求, 基于 LangGraph 状态图工作流与真实高德地图服务生成详细的旅行计划",
    responses={
        400: {"model": ErrorResponse, "description": "请求参数校验不通过"},
        500: {"model": ErrorResponse, "description": "行程计划生成失败"},
    },
)
async def plan_trip(request: TripRequest):
    """生成旅行计划 (LangGraph 引擎)

    Args:
        request: 旅行请求参数

    Returns:
        旅行计划响应
    """
    logger.info(
        f"收到旅行规划请求 | 城市: {request.city} | 日期: {request.start_date} ~ {request.end_date} | 天数: {request.travel_days} 天"
    )

    try:
        final_state = run_trip_planner_workflow(request)

        if final_state.get("is_failed"):
            error_msg = (
                final_state.get("error_message")
                or "生成旅行计划失败：未通过真实性校验或修补超限"
            )
            logger.error(f"旅行计划生成失败: {error_msg}")

            # 若属于前置输入参数校验未通过，返回 400 Bad Request
            is_input_validation_err = (
                not final_state.get("validation_passed")
                and final_state.get("draft_skeleton") is None
            )
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if is_input_validation_err
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            raise HTTPException(
                status_code=status_code,
                detail=error_msg,
            )

        final_plan = final_state.get("final_plan")
        if not final_plan:
            logger.error("工作流执行完毕但未能产出有效行程计划")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="旅行计划生成异常：未能生成有效计划数据",
            )

        logger.info(
            f"旅行计划生成成功 | 交付天数: {len(final_plan.days)} 天 | "
            f"总预算: {final_plan.budget.total if final_plan.budget else 0} 元"
        )

        return TripPlanResponse(
            success=True,
            message="旅行计划生成成功",
            data=final_plan,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"执行 LangGraph 旅行规划工作流发生未捕获异常: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"生成旅行计划失败: {str(e)}",
        )


@router.get(
    "/health",
    summary="健康检查",
    description="检查旅行规划 LangGraph 状态图引擎与服务是否正常",
)
async def health_check():
    """健康检查"""
    try:
        graph = get_trip_planner_graph()
        return {
            "status": "healthy",
            "service": "trip-planner",
            "engine": "langgraph-stategraph",
            "graph_compiled": graph is not None,
        }
    except Exception as e:
        logger.exception(f"旅行规划健康检查失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"服务不可用: {str(e)}",
        )
