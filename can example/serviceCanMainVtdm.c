#include "serviceCanMain.h"
#include "serviceMd.h"
#include "serviceParam.h"
#include "squeue.h"

// очередь на отправку
volatile item_t canTxA[CAN_QUEUE_SIZE];
volatile squeue_t canTx;

// приёмные очереди
volatile item_t canRxA[CAN_QUEUE_SIZE];
volatile squeue_t canRx;

volatile flag_t isCanMailboxFree[3];

// id, им присваиваются значения в зависимости от g_side
volatile uint32_t canGeneralStdId;
volatile uint32_t canNoticeStdId;
volatile uint32_t canServiceStdId;



void setNewApiCanBusFilters(void);
void setCanIrqParams(void);
int32_t parseCanMainMsg(item_t *item);


void TxMailbox0CompleteCallback(CAN_HandleTypeDef *hcan);
void TxMailbox1CompleteCallback(CAN_HandleTypeDef *hcan);
void TxMailbox2CompleteCallback(CAN_HandleTypeDef *hcan);
void RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan);
void RxFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan);


void canMain_Init(void){
	#ifdef DEBUG_SWO
			TM_SWO_Printf("\n CANMain init begin \n");
	#endif
	canTx.data = canTxA;
  canTx.data_size = CAN_QUEUE_SIZE;
  canTx.avail = CAN_QUEUE_SIZE;
  canTx.size = 0;
  canTx.head = 0;
  canTx.tail = 0;
  canTx.isTailUnlocked = true;
  canTx.isHeadUnlocked = true;

  canRx.data = canRxA;
  canRx.data_size = CAN_QUEUE_SIZE;
  canRx.avail = CAN_QUEUE_SIZE;
  canRx.size = 0;
  canRx.head = 0;
  canRx.tail = 0;
  canRx.isTailUnlocked = true;
  canRx.isHeadUnlocked = true;
	
	switch(vtdm_num){
		case 0:	canGeneralStdId	= CID_VTDMA_GENERAL;
						canNoticeStdId	= CID_VTDMA_NOTICE;
						canServiceStdId	= CID_VTDMA_SERVICE;  break;
		case 1:	canGeneralStdId	= CID_VTDMB_GENERAL;
						canNoticeStdId	= CID_VTDMB_NOTICE;
						canServiceStdId	= CID_VTDMB_SERVICE;  break;		
	}		

	isCanMailboxFree[0] = TRUE;
	isCanMailboxFree[1] = TRUE;
	isCanMailboxFree[2] = TRUE;	
	// Установка ABOM в единицу - автоматический выход из режима Buss-off, когда 
	// на CAN-шине будет "тишина" в течении времени передачи 11 бит * 128 раз
	// CAN1->MCR |= CAN_MCR_ABOM;
	setNewApiCanBusFilters();
	setCanIrqParams();

	// Регистрация callback-ов
	// Важно: регистрация происходит в STM32CubeMX Project Manager > Advanced Settings > Register Callback 
	HAL_CAN_RegisterCallback(&hcan1, HAL_CAN_RX_FIFO0_MSG_PENDING_CB_ID, RxFifo0MsgPendingCallback);
	HAL_CAN_RegisterCallback(&hcan1, HAL_CAN_RX_FIFO1_MSG_PENDING_CB_ID, RxFifo1MsgPendingCallback);   
	HAL_CAN_RegisterCallback(&hcan1, HAL_CAN_TX_MAILBOX0_COMPLETE_CB_ID, TxMailbox0CompleteCallback);
	HAL_CAN_RegisterCallback(&hcan1, HAL_CAN_TX_MAILBOX1_COMPLETE_CB_ID, TxMailbox1CompleteCallback);
	HAL_CAN_RegisterCallback(&hcan1, HAL_CAN_TX_MAILBOX2_COMPLETE_CB_ID, TxMailbox2CompleteCallback);
	
	if(HAL_OK != HAL_CAN_Start(&hcan1))
	{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CANmain (can1) not started\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CANmain (can1) has been started\n");
			#endif
	}
	if(HAL_OK != HAL_CAN_ActivateNotification(&hcan1,
																						CAN_IT_RX_FIFO0_MSG_PENDING | 
																						CAN_IT_TX_MAILBOX_EMPTY))
	{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CANmain (can1) not activated\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CANmain (can1) has been activated\n");
			#endif
	}

}

/**
	* @brief функция настройки фильтрации CAN сообщений
  * @retval None
  */
void setNewApiCanBusFilters(void) {
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

/**
	* @brief Функция настройки прерываний CAN интерфейса
	* @Warning Примечание: ф-ции инициализации HAL в явном виде не настраивают источники прерываний
  * @retval None
  */
void setCanIrqParams(void)
{                                  // прерывание при ...  
    CAN1->IER |= CAN_IER_TMEIE;   // освобождении исх. почт. ящика
    CAN1->IER |= CAN_IER_FMPIE0;  // получение пакета в FIFO0
    CAN1->IER &= ~CAN_IER_FFIE0;  // заполнении FIFO0 
    CAN1->IER |= CAN_IER_FOVIE0;  // переполнении FIFO0 
    CAN1->IER |= CAN_IER_FMPIE1;  // получение пакета в FIFO1
    CAN1->IER &= ~CAN_IER_FFIE1;  // заполнении FIFO1 
    CAN1->IER |= CAN_IER_FOVIE1;  // переполнении FIFO1
    CAN1->IER &= ~CAN_IER_EWGIE;  // дост-и пред-го (>= 96) ур-ня оши-к
    CAN1->IER |= CAN_IER_EPVIE;   // дост-и пассивного ур-ня ошибок
    CAN1->IER |= CAN_IER_BOFIE;   // переходе в режим bus-off
    CAN1->IER &= ~CAN_IER_LECIE;  // возникновении ошибки приёма-передачи
    CAN1->IER &= ~CAN_IER_ERRIE;  // возникновении ошибки
    CAN1->IER &= ~CAN_IER_WKUIE;  // выходе из спящего режима
    CAN1->IER &= ~CAN_IER_SLKIE;  // переходе в спящий режим
}
    

void canMain_execTx(void){			///> обработка очереди на отправку в CAN
		HAL_StatusTypeDef ret;
		if(canTx.size && (isCanMailboxFree[0] | 
												 isCanMailboxFree[1] |
												 isCanMailboxFree[2])){
				new_api_canmsg_t *pMsg = sq_head((squeue_t*)&canTx);
				uint32_t mailbox;
				if(NULL != pMsg)				{
						ret = HAL_CAN_AddTxMessage(&hcan1, (CAN_TxHeaderTypeDef*)&pMsg->header, pMsg->data, &mailbox);
						if(HAL_OK == ret){
								isCanMailboxFree[mailbox] = FALSE;
								sq_remove_head((squeue_t*)&canTx);
						}else{}                
//								TM_SWO_Printf("Can message send error, ret = %u \n", ret);
				}
		#ifdef DEBUG_SWO
				else{
						TM_SWO_Printf("Can tx message error. Msg is null!");
				}
		#endif
		}
}

void canMain_execRx(void){   ///> обработка входящих сообщений в CAN
		if(canRx.size)
		{
				item_t* msgp = sq_head((squeue_t*)&canRx);
				if(NULL != msgp)
				{
						int ret = parseCanMainMsg(msgp);
//						if((-1) != ret)
						sq_remove_head((squeue_t*)&canRx);
				}
		}	
}


int32_t parseCanMainMsg(item_t *item)	{
	if(NULL == item)
		return -1;
	  switch(item->header.StdId){
        case CID_ECU_NOTICE:
        case CID_ECU_GENERAL:
        case CID_ECU_SERVICE:
				{
            switch(item->dataStruct.identifier.um){
							case CANMSG_ECU_TO_VTDM_START:						smd_cmdStart.init		= 1;		break; 
							case CANMSG_ECU_TO_VTDM_STOP:							smd_cmdStop.init		= 1;		break;
							case CANMSG_ECU_TO_VTDM_DEBLOCK:					smd_cmdDeblock.init	= 1;		break;			
							case CANMSG_ECU_TO_VTDM_MODE_REQ:					canMain_sendOpMode();				break;
							case CANMSG_ECU_TO_VTDM_SERV_START:				smd_cmdServStart.init = 1;	break;
							case CANMSG_ECU_TO_VTDM_SERV_STOP:				smd_cmdServStop.init = 1;		break;
							case CANMSG_CFG_ON: 								if(vtdm_num == item->dataStruct.code.um)	
																											//paramConfigMdOn();	
																										break;
							case CANMSG_CFG_WRITEPARAM:				if(cfgMdDummy){ 
																											PARAM_WRITE_UINT32(item->dataStruct.code.um, item->dataStruct.value.uw);
																											//can_sendParamVal(item->dataStruct.code.um);																													
																										}break;
							case CANMSG_CFG_RAEDPARAM:					if(vtdm_num == item->dataStruct.code.um)					
																											//can_sendParamVal(item->dataStruct.value.um[1]); 		
																										break;	
							case CANMSG_CFG_ACCEPTPARAM:				if(cfgMdDummy)
																											//paramAccept();				
																										break;
							case CANMSG_CFG_CRCPARAM_REQ:			if(vtdm_num == item->dataStruct.code.um)
																											//can_sendParamCrcval();
																										break;	
							default:			return -1;
						}
				}
	}
	return 0;
}



void canMain_sendError(uint16_t error){
	  static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_VTDM_ERROR	
    };
		msg.header.StdId = canNoticeStdId;
    msg.dataStruct.value.uw = error;				
		int ret = sq_insert_head((squeue_t*)&canTx, &msg);
		#ifdef DEBUG_SWO
				if(ret < 0){
            TM_SWO_Printf("sq_insert_head error in sendOpMode, ret = %d", ret);
        }
    #endif
}

void canMain_sendPing(float temp){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_VTDM_PING	
    };
    msg.header.StdId = canNoticeStdId;
    msg.dataStruct.value.f = temp;	
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
			if(ret < 0){
				TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canTx.size);
			}
    #endif
}

void canMain_sendStatreg(StatRegVal_t* val){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_VTDM_STATREG_VAL	
    };
    msg.header.StdId = canNoticeStdId;
		msg.dataStruct.code.um = val->regNum;
		msg.dataStruct.value.uw = val->val;
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
			if(ret < 0){
				TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canTx.size);
			}
    #endif
}




void canMain_sendOpMode(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_VTDM_MODE	
    };
    msg.header.StdId = canGeneralStdId;
    msg.dataStruct.value.um[0] = md_vtdmMode;	
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canTx.size);
      }
   #endif
}

void can_sendParamVal(uint16_t paramCode){
/*    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_CFG_PARAMVAL	
    };
		if(paramCode < PARAM_REG_SIZE){
			msg.header.StdId = can1NoticeStdId;
			msg.dataStruct.code.um	=	paramCode;
			msg.dataStruct.value.uw	=	paramMap.uw[paramCode];
			int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
			#ifndef DEBUG_SWO  
				if(ret < 0){
          TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d", ret);
				}
			#endif
		}*/
}


void can_sendCfgReady(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_VTDM_CFG_READY	
    };
    msg.header.StdId = canNoticeStdId;
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
        if(ret < 0){
            TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d", ret);
        }
    #endif
}

void can_sendCfgConfirm(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_VTDM_CFG_CONFIRM	
    };
    msg.header.StdId = canNoticeStdId;
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
        if(ret < 0){
            TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d", ret);
        }
    #endif
}

void can_sendParamCrcval(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANMSG_VTDM_CFG_CRCVAL	
    };
    msg.header.StdId = canNoticeStdId;
//		msg.dataStruct.value.uw	=	paramCrc;
		int ret = sq_insert_tail((squeue_t*)&canTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
          TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d", ret);
     }
    #endif
}


void TxMailbox0CompleteCallback(CAN_HandleTypeDef *hcan){
    isCanMailboxFree[0] = TRUE;
}
void TxMailbox1CompleteCallback(CAN_HandleTypeDef *hcan){
    isCanMailboxFree[1] = TRUE;
}
void TxMailbox2CompleteCallback(CAN_HandleTypeDef *hcan){
    isCanMailboxFree[2] = TRUE;
}

void RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO0, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(canRx.avail){
				sq_insert_tail((squeue_t*)&canRx, &item);
		}
		return;
}

void RxFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO1, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(canRx.avail){
				sq_insert_tail((squeue_t*)&canRx, &item);
		}
		return;
}


