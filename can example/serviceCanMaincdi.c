#include "serviceCanMain.h"
#include "squeue.h"
#include "serviceMd.h"
#include "service.h"

// очередь на отправку
volatile item_t canTxA[CANMAIN_QUEUE_SIZE];
volatile squeue_t canTx;

// приёмные очереди
volatile item_t canRxA[CANMAIN_QUEUE_SIZE];
volatile squeue_t canRx;

// id, им присваиваются значения в зависимости от g_side
volatile uint32_t canGeneralStdId;
volatile uint32_t canNoticeStdId;
volatile uint32_t canServiceStdId;


void canMain_Init(void){
	#ifdef DEBUG_SWO
		TM_SWO_Printf("\nFDCAN_Main init begin\n");
	#endif	
	
	canTx.data = canTxA;
  canTx.data_size = CANMAIN_QUEUE_SIZE;
  canTx.avail = CANMAIN_QUEUE_SIZE;
  canTx.size = 0;
  canTx.head = 0;
  canTx.tail = 0;
  canTx.isTailUnlocked = true;
  canTx.isHeadUnlocked = true;

  canRx.data = canRxA;
  canRx.data_size = CANMAIN_QUEUE_SIZE;
  canRx.avail = CANMAIN_QUEUE_SIZE;
  canRx.size = 0;
  canRx.head = 0;
  canRx.tail = 0;
  canRx.isTailUnlocked = true;
  canRx.isHeadUnlocked = true;

	switch(g_cdiNum){
		case CDI_A1:
			canGeneralStdId 	= CID_CDIA_GENERAL;
			canNoticeStdId 		= CID_CDIA_NOTICE;
			canServiceStdId 	= CID_CDIA_SERVICE;
		break;
		case CDI_A2:
			canGeneralStdId 	= CID_CDIB_GENERAL;
			canNoticeStdId 		= CID_CDIB_NOTICE;
			canServiceStdId 	= CID_CDIB_SERVICE;
		break;
		case CDI_B1:
			canGeneralStdId 	= CID_CDIC_GENERAL;
			canNoticeStdId 		= CID_CDIC_NOTICE;
			canServiceStdId 	= CID_CDIC_SERVICE;
		break;
		case CDI_B2:
			canGeneralStdId 	= CID_CDID_GENERAL;
			canNoticeStdId 		= CID_CDID_NOTICE;
			canServiceStdId 	= CID_CDID_SERVICE;
		break;		
	}
	
	if(HAL_FDCAN_Start(&hfdcan2) != HAL_OK){
			#ifdef DEBUG_SWO
					TM_SWO_Printf("FDCAN_Main not started!\n");
			#endif	
			Error_Handler();
	}

	if(HAL_FDCAN_ActivateNotification(&hfdcan2, FDCAN_IT_RX_FIFO0_NEW_MESSAGE, 0) != HAL_OK){
			#ifdef DEBUG_SWO
					TM_SWO_Printf("FDCAN_Main notification not started!\n");
			#endif	
			Error_Handler();
	}
	
	setCanBusFilters(); // Инициализация фильтра сообщений CAN-шины
}


void setCanBusFilters(void) {
	FDCAN_FilterTypeDef sFilterConfig;

	sFilterConfig.IdType = FDCAN_STANDARD_ID;
	sFilterConfig.FilterIndex = 0;
	sFilterConfig.FilterType = FDCAN_FILTER_MASK;
	sFilterConfig.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
	sFilterConfig.FilterID1 = 0x0;
	sFilterConfig.FilterID2 = 0x0;
	if (HAL_FDCAN_ConfigFilter(&hfdcan2, &sFilterConfig) != HAL_OK){
		/* Filter configuration Error */
		#ifdef DEBUG_SWO
             TM_SWO_Printf("FDCAN_Main filter config error");
		#endif	
		Error_Handler();
	}	
}


void canMain_sendError(uint16_t error){
	  static item_t msg = {
				.header.IdType							=	FDCAN_STANDARD_ID,
				.header.TxFrameType					=	FDCAN_DATA_FRAME,	
				.header.DataLength					=	FDCAN_DLC_BYTES_8,			
				.header.ErrorStateIndicator = FDCAN_ESI_ACTIVE,
				.header.BitRateSwitch				= FDCAN_BRS_OFF,
				.header.FDFormat						= FDCAN_CLASSIC_CAN,
				.header.TxEventFifoControl	= FDCAN_NO_TX_EVENTS,
				.header.MessageMarker				= 0,			
				.dataStruct.identifier.um = CANMSG_CDI_ERROR	
    };
		msg.header.Identifier = canNoticeStdId;
    msg.dataStruct.value.uw = error;				
		int ret = sq_insert_head((squeue_t*)&canTx, &msg);
		#ifdef DEBUG_SWO
				if(ret < 0){
            TM_SWO_Printf("sq_insert_head error in sendError, ret = %d", ret);
        }
    #endif
}


void canMain_sendPing(float temp){
    static item_t msg = {			
				.header.IdType							=	FDCAN_STANDARD_ID,
				.header.TxFrameType					=	FDCAN_DATA_FRAME,	
				.header.DataLength					=	FDCAN_DLC_BYTES_8,			
				.header.ErrorStateIndicator = FDCAN_ESI_ACTIVE,
				.header.BitRateSwitch				= FDCAN_BRS_OFF,
				.header.FDFormat						= FDCAN_CLASSIC_CAN,
				.header.TxEventFifoControl	= FDCAN_NO_TX_EVENTS,
				.header.MessageMarker				= 0,			
				.dataStruct.identifier.um = CANMSG_CDI_PING	
    };
    msg.header.Identifier = canNoticeStdId;
    msg.dataStruct.value.f = temp;	
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
			if(ret < 0){
//				TM_SWO_Printf("sq_insert_tail error in sendPing, ret = %d, size = %ui \n", ret, canTx.size);
			}
    #endif
}


void canMain_sendCdiCut(uint16_t val){
    static item_t msg = {			
				.header.IdType							=	FDCAN_STANDARD_ID,
				.header.TxFrameType					=	FDCAN_DATA_FRAME,	
				.header.DataLength					=	FDCAN_DLC_BYTES_8,			
				.header.ErrorStateIndicator = FDCAN_ESI_ACTIVE,
				.header.BitRateSwitch				= FDCAN_BRS_OFF,
				.header.FDFormat						= FDCAN_CLASSIC_CAN,
				.header.TxEventFifoControl	= FDCAN_NO_TX_EVENTS,
				.header.MessageMarker				= 0,			
				.dataStruct.identifier.um 	= CANMSG_CDI_FLTCUT	
    };
    msg.header.Identifier = canNoticeStdId;
    msg.dataStruct.value.um[0] = val;	
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
			if(ret < 0){
//				TM_SWO_Printf("sq_insert_tail error in sendPing, ret = %d, size = %ui \n", ret, canTx.size);
			}
    #endif
}


void canMain_sendOpMode(void){
    static item_t msg = {			
				.header.IdType							=	FDCAN_STANDARD_ID,
				.header.TxFrameType					=	FDCAN_DATA_FRAME,	
				.header.DataLength					=	FDCAN_DLC_BYTES_8,			
				.header.ErrorStateIndicator = FDCAN_ESI_ACTIVE,
				.header.BitRateSwitch				= FDCAN_BRS_OFF,
				.header.FDFormat						= FDCAN_CLASSIC_CAN,
				.header.TxEventFifoControl	= FDCAN_NO_TX_EVENTS,
				.header.MessageMarker				= 0,			

				.dataStruct.identifier.um = CANMSG_CDI_MODE	
    };
    msg.header.Identifier = canGeneralStdId;
		msg.dataStruct.value.um[0] = smd_cdiMode;
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
			if(ret < 0){
				TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canTx.size);
			}
    #endif	
}


// обработка очереди на отправку в CANFD
void canMain_execTx(void){
	HAL_StatusTypeDef ret;
	if(canTx.size){
				item_t *pMsg = sq_head((squeue_t*)&canTx);
				if(pMsg != NULL)
					ret = HAL_FDCAN_AddMessageToTxFifoQ(&hfdcan2, (FDCAN_TxHeaderTypeDef*)&pMsg->header, pMsg->data);			
				if(ret == HAL_OK){
					sq_remove_head((squeue_t*)&canTx);
					//TM_SWO_Printf("Can message send OK, ret = %u \n", ret);
				}else{                
//					TM_SWO_Printf("Can message send error, ret = %u \n", ret);
				}
	}
}

int32_t parseCanMainMsg(item_t *pMsg);

// обработка очереди входящих сообщений из CANFD
void canMain_execRx(void){
	if(canRx.size){
		item_t* msgp = sq_head((squeue_t*)&canRx);
		if(msgp != NULL){
			int ret = parseCanMainMsg(msgp);
			sq_remove_head((squeue_t*)&canRx);
		}
	}	
}

// парсер входящих сообщений из CANFD 
int32_t parseCanMainMsg(item_t *pMsg)	{
	if(pMsg == NULL)
		return -1;
	  switch(pMsg->header.Identifier){
        case CID_ECU_NOTICE:
        case CID_ECU_GENERAL:
        case CID_ECU_SERVICE:
				{
            switch(pMsg->dataStruct.identifier.um){
							case CANMSG_ECU_START:							smd_Main_cmdStart.init		= 1;		break; 
							case CANMSG_ECU_STOP:								smd_Main_cmdStop.init			= 1;		break;
							case CANMSG_ECU_DEBLOCK:						smd_Main_cmdDeblock.init	= 1;		break;			
							case CANMSG_ECU_MODE_REQ:						canMain_sendOpMode();							break;
							case CANMSG_ECU_TO_CDI_SERV_START:	smd_Main_cmdServStart.init = 1;		break;
							case CANMSG_ECU_TO_CDI_SERV_STOP:		smd_Main_cmdServStop.init 	= 1;	break;
							case CANMSG_CFG_ON: 								if(g_cdiNum == pMsg->dataStruct.code.um)	
																											//paramConfigMdOn();	
																										break;
							case CANMSG_CFG_WRITEPARAM:				if(cfgMdDummy){ 
																											//PARAM_WRITE_UINT32(item->dataStruct.code.um, item->dataStruct.value.uw);
																											//can_sendParamVal(item->dataStruct.code.um);																													
																										}break;
							case CANMSG_CFG_RAEDPARAM:					if(g_cdiNum == pMsg->dataStruct.code.um)					
																											//can_sendParamVal(item->dataStruct.value.um[1]); 		
																										break;	
							case CANMSG_CFG_ACCEPTPARAM:				if(cfgMdDummy)
																											//paramAccept();				
																										break;
							case CANMSG_CFG_CRCPARAM_REQ:			if(g_cdiNum == pMsg->dataStruct.code.um)
																											//can_sendParamCrcval();
																										break;	
							default:			return -1;
						}
				}
	}	
	return 0;
}


void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *hfdcan, uint32_t RxFifo0ITs){
		item_t pMsg;
		if((RxFifo0ITs & FDCAN_IT_RX_FIFO0_NEW_MESSAGE) != RESET){
    /* Retreive Rx messages from RX FIFO0 */
    if(HAL_FDCAN_GetRxMessage(hfdcan, FDCAN_RX_FIFO0, (FDCAN_RxHeaderTypeDef*)&pMsg.header, pMsg.data) != HAL_OK){
			/* Reception Error */
			Error_Handler();
    }
		if(canRx.avail){
			sq_insert_tail((squeue_t*)&canRx, &pMsg);
		}		
    if(HAL_FDCAN_ActivateNotification(hfdcan, FDCAN_IT_RX_FIFO0_NEW_MESSAGE, 0) != HAL_OK){
			/* Notification Error */
			Error_Handler();
    }
  }
}

