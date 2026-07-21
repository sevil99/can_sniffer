#include "serviceCanMain.h"


/**
	* @brief функция настройки фильтрации CAN сообщений
  * @retval None
  */
void canMain_setNewApiCanBusFilters(void) {
    CAN_FilterTypeDef can1Filter = {
//        .FilterIdHigh						=	CID_MRTK_NOTICE<<5, // 0x0000,		  								//CID_ICM_GENERAL		<< 5
//        .FilterIdLow						=	CID_MRTK_GENERAL<<5, //0x0000,											//CID_CFG1_GENERAL	<< 5
//        .FilterMaskIdHigh				=	CID_MRTK_SERVICE<<5, //0x0000,											//CID_ICM_NOTICE		<< 5 
//        .FilterMaskIdLow				=	CID_MRTK_SERVICE<<5,	//0x0000,											//CID_CFG1_NOTICE		<< 5
        .FilterIdHigh						=	0x0000, 
        .FilterIdLow						=	0x0000, 
        .FilterMaskIdHigh				=	0x0000, 
        .FilterMaskIdLow				=	0x0000,				
        .FilterFIFOAssignment		=	CAN_RX_FIFO0,								//
        .FilterBank							=	0,
        .FilterMode							=	CAN_FILTERMODE_IDMASK,			//CAN_FILTERMODE_IDLIST
        .FilterScale						=	CAN_FILTERSCALE_16BIT,			//CAN_FILTERSCALE_16BIT
        .FilterActivation				=	ENABLE,
        .SlaveStartFilterBank		=	14 };
    if(HAL_OK != HAL_CAN_ConfigFilter(&hcan1, &can1Filter)){
        #ifdef DEBUG_SWO
             TM_SWO_Printf("CAN filter config error");
        #endif
        Error_Handler();
    }		
}
