#include"serviceCanVlv.h"
#include"serviceMd.h"
//#include"serviceParam.h"
#include"squeue.h"
#include"defines.h"
#include"serviceParam.h"

// очередь на отправку
volatile item_t canVlvTxA[CANVLV_QUEUE_SIZE];
volatile squeue_t canVlvTx;

// приёмные очереди
volatile item_t canVlvRxA[CANVLV_QUEUE_SIZE];
volatile squeue_t canVlvRx;

volatile flag_t isCanVlvMailboxFree[3];

// id, им присваиваются значения в зависимости от g_side
volatile uint32_t canVlvGeneralStdId;
volatile uint32_t canVlvNoticeStdId;
volatile uint32_t canVlvServiceStdId;



void setVlvNewApiCanBusFilters(void);
void setVlvCanIrqParams(void);
int32_t parseCanVlvMsg(item_t *item);


void TxVlvMailbox0CompleteCallback(CAN_HandleTypeDef *hcan);
void TxVlvMailbox1CompleteCallback(CAN_HandleTypeDef *hcan);
void TxVlvMailbox2CompleteCallback(CAN_HandleTypeDef *hcan);
void RxVlvFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan);
void RxVlvFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan);


void canVlv_Init(void){
	#ifdef DEBUG_SWO
			TM_SWO_Printf("\n CANVlv init begin \n");
	#endif
	canVlvTx.data = canVlvTxA;
  canVlvTx.data_size = CANVLV_QUEUE_SIZE;
  canVlvTx.avail = CANVLV_QUEUE_SIZE;
  canVlvTx.size = 0;
  canVlvTx.head = 0;
  canVlvTx.tail = 0;
  canVlvTx.isTailUnlocked = true;
  canVlvTx.isHeadUnlocked = true;

  canVlvRx.data = canVlvRxA;
  canVlvRx.data_size = CANVLV_QUEUE_SIZE;
  canVlvRx.avail = CANVLV_QUEUE_SIZE;
  canVlvRx.size = 0;
  canVlvRx.head = 0;
  canVlvRx.tail = 0;
  canVlvRx.isTailUnlocked = true;
  canVlvRx.isHeadUnlocked = true;
	
	canVlvGeneralStdId 	= CIDVLV_MRTK_GENERAL;
	canVlvNoticeStdId 	= CIDVLV_MRTK_NOTICE;
	canVlvServiceStdId 	= CIDVLV_MRTK_SERVICE; 

	isCanVlvMailboxFree[0] = TRUE;
	isCanVlvMailboxFree[1] = TRUE;
	isCanVlvMailboxFree[2] = TRUE;	
	// Установка ABOM в единицу - автоматический выход из режима Buss-off, когда 
	// на CAN-шине будет "тишина" в течении времени передачи 11 бит * 128 раз
	// CAN1->MCR |= CAN_MCR_ABOM;
	setVlvNewApiCanBusFilters();
	setVlvCanIrqParams();

	// Регистрация callback-ов
	// Важно: регистрация происходит в STM32CubeMX Project Manager > Advanced Settings > Register Callback 
	TM_SWO_Printf("reg cb ret=%u\n", HAL_CAN_RegisterCallback(&hcan2, HAL_CAN_RX_FIFO0_MSG_PENDING_CB_ID, RxVlvFifo0MsgPendingCallback));
	TM_SWO_Printf("reg cb ret=%u\n", HAL_CAN_RegisterCallback(&hcan2, HAL_CAN_RX_FIFO1_MSG_PENDING_CB_ID, RxVlvFifo1MsgPendingCallback));   
	TM_SWO_Printf("reg cb ret=%u\n", HAL_CAN_RegisterCallback(&hcan2, HAL_CAN_TX_MAILBOX0_COMPLETE_CB_ID, TxVlvMailbox0CompleteCallback));
	TM_SWO_Printf("reg cb ret=%u\n", HAL_CAN_RegisterCallback(&hcan2, HAL_CAN_TX_MAILBOX1_COMPLETE_CB_ID, TxVlvMailbox1CompleteCallback));
	TM_SWO_Printf("reg cb ret=%u\n", HAL_CAN_RegisterCallback(&hcan2, HAL_CAN_TX_MAILBOX2_COMPLETE_CB_ID, TxVlvMailbox2CompleteCallback));
	
	if(HAL_OK != HAL_CAN_Start(&hcan2))
	{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CANVlv (can2) not started\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CANvlv (can2) has been started\n");
			#endif
	}
	
	if(HAL_OK != HAL_CAN_ActivateNotification(&hcan2,
																						CAN_IT_RX_FIFO0_MSG_PENDING | 
																						CAN_IT_TX_MAILBOX_EMPTY))
	{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("\nCANvlv (can2) not activated\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CANvlv (can2) has been activated\n");
			#endif
	}

}

/**
	* @brief функция настройки фильтрации CAN сообщений
  * @retval None
  */
void setVlvNewApiCanBusFilters(void) {
    CAN_FilterTypeDef can1Filter = {
//        .FilterIdHigh						=	CIDVLV_VCU1_NOTICE|CIDVLV_VCU1_GENERAL|CIDVLV_VCU1_SERVICE<<5, // 0x0000,		  								//CID_ICM_GENERAL		<< 5
//        .FilterIdLow						=	0xFFF0<<5, //0x0000,											//CID_CFG1_GENERAL	<< 5
//        .FilterMaskIdHigh				=	0x0000<<5, //0x0000,											//CID_ICM_NOTICE		<< 5 
//        .FilterMaskIdLow				=	0x0000<<5,	//0x0000,											//CID_CFG1_NOTICE		<< 5
//        .FilterIdHigh						=	0x0000, 
        .FilterIdHigh						=	0x0000, 
        .FilterIdLow						=	0x0000, 
        .FilterMaskIdHigh				=	0x0000, 
        .FilterMaskIdLow				=	0x0000,
        .FilterFIFOAssignment		=	CAN_RX_FIFO0,								//
        .FilterBank							=	0,
        .FilterMode							=	CAN_FILTERMODE_IDMASK, //CAN_FILTERMODE_IDLIST,			//CAN_FILTERMODE_IDMASK 
        .FilterScale						=	CAN_FILTERSCALE_32BIT,			//CAN_FILTERSCALE_16BIT
        .FilterActivation				=	ENABLE,
       // .SlaveStartFilterBank		=	14 
			};
    if(HAL_OK != HAL_CAN_ConfigFilter(&hcan2, &can1Filter)){
        #ifdef DEBUG_SWO
             TM_SWO_Printf("CAN filter config error");
        #endif
        Error_Handler();
    }
		/*
		    CAN_FilterTypeDef can2Filter = {
        .FilterIdHigh =         0x0000,
        .FilterIdLow =          0x0000,
        .FilterMaskIdHigh =     0x0000, 
        .FilterMaskIdLow =      0x0000,
        .FilterFIFOAssignment = CAN_RX_FIFO0,
        .FilterBank =           14,
        .FilterMode =           CAN_FILTERMODE_IDMASK,
        .FilterScale =          CAN_FILTERSCALE_32BIT,
        .FilterActivation =     ENABLE,
        .SlaveStartFilterBank = 14 };
    
    if(HAL_OK != HAL_CAN_ConfigFilter(&hcan2, &can2Filter))
    {
        #ifdef DEBUG
             TM_SWO_Printf("CAN2 filter config error");
        #endif
        Error_Handler();
    }
*/
		
}

/**
	* @brief Функция настройки прерываний CAN интерфейса
	* @Warning Примечание: ф-ции инициализации HAL в явном виде не настраивают источники прерываний
  * @retval None
  */
void setVlvCanIrqParams(void)
{                                  // прерывание при ...  
    CAN2->IER |= CAN_IER_TMEIE;   // освобождении исх. почт. ящика
    CAN2->IER |= CAN_IER_FMPIE0;  // получение пакета в FIFO0
    CAN2->IER &= ~CAN_IER_FFIE0;  // заполнении FIFO0 
    CAN2->IER |= CAN_IER_FOVIE0;  // переполнении FIFO0 
    CAN2->IER |= CAN_IER_FMPIE1;  // получение пакета в FIFO1
    CAN2->IER &= ~CAN_IER_FFIE1;  // заполнении FIFO1 
    CAN2->IER |= CAN_IER_FOVIE1;  // переполнении FIFO1
    CAN2->IER &= ~CAN_IER_EWGIE;  // дост-и пред-го (>= 96) ур-ня оши-к
    CAN2->IER |= CAN_IER_EPVIE;   // дост-и пассивного ур-ня ошибок
    CAN2->IER |= CAN_IER_BOFIE;   // переходе в режим bus-off
    CAN2->IER &= ~CAN_IER_LECIE;  // возникновении ошибки приёма-передачи
    CAN2->IER &= ~CAN_IER_ERRIE;  // возникновении ошибки
    CAN2->IER &= ~CAN_IER_WKUIE;  // выходе из спящего режима
    CAN2->IER &= ~CAN_IER_SLKIE;  // переходе в спящий режим
/*
		CAN2->IER &= ~CAN_IER_TMEIE;  // освобождении исх. почт. ящика
    CAN2->IER |= CAN_IER_FMPIE0;  // получение пакета в FIFO0
    CAN2->IER |= CAN_IER_FFIE0;   // заполнении FIFO0 
    CAN2->IER |= CAN_IER_FOVIE0;  // переполнении FIFO0 
    CAN2->IER |= CAN_IER_FMPIE1;  // получение пакета в FIFO1
    CAN2->IER |= CAN_IER_FFIE1;   // заполнении FIFO1 
    CAN2->IER |= CAN_IER_FOVIE1;  // переполнении FIFO1
    CAN2->IER &= ~CAN_IER_EWGIE;  // дост-и пред-го (>= 96) ур-ня оши-к
    CAN2->IER &= ~CAN_IER_EPVIE;  // дост-и пассивного ур-ня ошибок
    CAN2->IER |= CAN_IER_BOFIE;   // переходе в режим bus-off
    CAN2->IER &= ~CAN_IER_LECIE;  // возникновении ошибки приёма-передачи
    CAN2->IER |= CAN_IER_ERRIE;   // возникновении ошибки
    CAN2->IER &= ~CAN_IER_WKUIE;  // выходе из спящего режима
    CAN2->IER &= ~CAN_IER_SLKIE;  // переходе в спящий режим
*/
/*
		CAN1->IER |= CAN_IER_TMEIE;   // освобождении исх. почт. ящика
    CAN1->IER |= CAN_IER_FMPIE0;  // получение пакета в FIFO0
		CAN1->IER &= ~CAN_IER_FFIE0;  // заполнении FIFO0 
    CAN1->IER |= CAN_IER_FOVIE0;  // переполнении FIFO0 
    CAN1->IER |= CAN_IER_FMPIE1;  // получение пакета в FIFO1
		СAN1->IER &= ~CAN_IER_FFIE1;  // заполнении FIFO1 
    CAN1->IER |= CAN_IER_FOVIE1;  // переполнении FIFO1
    CAN1->IER &= ~CAN_IER_EWGIE;  // дост-и пред-го (>= 96) ур-ня оши-к
		CAN1->IER |= CAN_IER_EPVIE;   // дост-и пассивного ур-ня ошибок
    CAN1->IER |= CAN_IER_BOFIE;   // переходе в режим bus-off
    CAN1->IER &= ~CAN_IER_LECIE;  // возникновении ошибки приёма-передачи
		CAN1->IER &= ~CAN_IER_ERRIE;  // возникновении ошибки
    CAN1->IER &= ~CAN_IER_WKUIE;  // выходе из спящего режима
    CAN1->IER &= ~CAN_IER_SLKIE;  // переходе в спящий режим
*/
}
    
                                  // прерывание при ...  




		
void canVlv_execTx(void){			///> обработка очереди на отправку в CAN
		HAL_StatusTypeDef ret;
		if(canVlvTx.size && (isCanVlvMailboxFree[0] | 
												 isCanVlvMailboxFree[1] |
												 isCanVlvMailboxFree[2])){
				new_api_canmsg_t *pMsg = sq_head((squeue_t*)&canVlvTx);
				uint32_t mailbox;
				if(NULL != pMsg)				{
//					TM_SWO_Printf( "CANvlv (can2) state = %u inserting Tx message \n", HAL_CAN_GetState(&hcan2)); 
					ret = HAL_CAN_AddTxMessage(&hcan2, (CAN_TxHeaderTypeDef*)&pMsg->header, pMsg->data, &mailbox);
//						TM_SWO_Printf("HAL_CAN_AddTxMessage hcan2 return val = %u \n", ret);
						if(HAL_OK == ret){
								isCanVlvMailboxFree[mailbox] = FALSE;
								sq_remove_head((squeue_t*)&canVlvTx);
						}else     {}           
//								TM_SWO_Printf("Can vlv message send error, ret = %u \n", ret);
//					TM_SWO_Printf( "CANvlv (can2) state = %u insert Tx message complete \n", HAL_CAN_GetState(&hcan2)); 
				}
		#ifdef DEBUG_SWO
				else{
						TM_SWO_Printf("Can tx message error. Msg is null!");
				}
		#endif
		}
}

void canVlv_execRx(void){   ///> обработка входящих сообщений в CAN
		if(canVlvRx.size)
		{
				item_t* msgp = sq_head((squeue_t*)&canVlvRx);
				if(NULL != msgp)
				{
						int ret = parseCanVlvMsg(msgp);
//						if((-1) != ret)
								sq_remove_head((squeue_t*)&canVlvRx);
				}
		}	
}


int32_t parseCanVlvMsg(item_t *item)	{
	static int32_t vcu_num;
	if(NULL == item)
		return -1;
  switch(item->header.StdId){
				case CIDVLV_VCU1_NOTICE:
				case CIDVLV_VCU1_GENERAL:
				case CIDVLV_VCU1_SERVICE:		vcu_num = 0; 	break; 
				case CIDVLV_VCU2_NOTICE:
				case CIDVLV_VCU2_GENERAL:
				case CIDVLV_VCU2_SERVICE:		vcu_num = 1; 	break; 
				case CIDVLV_VCU3_NOTICE:
				case CIDVLV_VCU3_GENERAL:
				case CIDVLV_VCU3_SERVICE:		vcu_num = 2; 	break; 
				case CIDVLV_VCU4_NOTICE:
				case CIDVLV_VCU4_GENERAL:
				case CIDVLV_VCU4_SERVICE:		vcu_num = 3; 	break; 
				case CIDVLV_VCU5_NOTICE:
				case CIDVLV_VCU5_GENERAL:
				case CIDVLV_VCU5_SERVICE:		vcu_num = 4; 	break; 
				case CIDVLV_VCU6_NOTICE:
				case CIDVLV_VCU6_GENERAL:
				case CIDVLV_VCU6_SERVICE:		vcu_num = 5; 	break; 
				case CIDVLV_VCU7_NOTICE:
				case CIDVLV_VCU7_GENERAL:
				case CIDVLV_VCU7_SERVICE:		vcu_num = 6; 	break; 
				case CIDVLV_VCU8_NOTICE:
				case CIDVLV_VCU8_GENERAL:
				case CIDVLV_VCU8_SERVICE:		vcu_num = 7; 	break; 
				case CIDVLV_VCU9_NOTICE:
				case CIDVLV_VCU9_GENERAL:
				case CIDVLV_VCU9_SERVICE:		vcu_num = 8; 	break; 
				case CIDVLV_VCU10_NOTICE:
				case CIDVLV_VCU10_GENERAL:
				case CIDVLV_VCU10_SERVICE:	vcu_num = 9; 	break; 
				default: 		vcu_num =  -1;
	}
	if(vcu_num >= 0){
		switch(item->dataStruct.identifier.um){
			case CANVLVMSG_VCU_PING:{
						vcuSubmduleArr[vcu_num].cntrPing++;
						vcuSubmduleArr[vcu_num].tempVal = item->dataStruct.value.f;
						break;
			}
			case CANVLVMSG_VCU_MODE:			{
						vcuSubmduleArr[vcu_num].cntrPing++;
						vcuSubmduleArr[vcu_num].submodMd = item->dataStruct.value.um[0];
						break;
			} 				
			case CANVLVMSG_VCU_ERROR:	{		
						vcuSubmduleArr[vcu_num].cntrPing++;
						vcuSubmduleArr[vcu_num].submodError = item->dataStruct.value.uw;
//						TM_SWO_Printf( "VCU submod error Vcu num = %u Erropr code = %u \n", vcu_num, item->dataStruct.value.uw); 
						break;
			}
			case CANVLVMSG_CFG_READY:			{
				serviceVcuCfgRedyRecieve(vcu_num);
				break; 					
			}
			case CANVLVMSG_CFG_PARAMVAL:	{
				serviceVcuParamRecieve(vcu_num, item->dataStruct.code.um, item->dataStruct.value.uw);
				break;
			}
			case CANVLVMSG_CFG_CONFIRM:		{
				serviceVcuCfgCofirmRecieve();
				break; 				
			}
			case CANVLVMSG_CFG_CRCVAL:		{
						vcuSubmduleArr[vcu_num].cntrPing++;
						vcuSubmduleArr[vcu_num].prm.crcVal = item->dataStruct.value.uw;
						vcuSubmduleArr[vcu_num].prm.isCrcValRecieved = true;
				break;
			}
			default: 		return -1;
		}
	}
	return 0;
}


void canVlv_sendPing(float temp){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_VCU_PING	
    };
//		TM_SWO_Printf("sendPing \n");
    msg.header.StdId = canVlvNoticeStdId;
    msg.dataStruct.value.f = temp;	
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
			if(ret < 0){
				TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canVlvTx.size);
			}
    #endif
}

/*
void canvlv_sendStart(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_MRTK_START	
    };
    msg.header.StdId = canVlvGeneralStdId;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}*/

void canvlv_sendStop(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_MRTK_STOP	
    };
    msg.header.StdId = canVlvNoticeStdId;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}

void canvlv_sendDeblock(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_MRTK_DEBLOCK	
    };
    msg.header.StdId = canVlvGeneralStdId;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}

void canvlv_sendMdRequest(){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_MRTK_TO_VCU_MODE_REQ	
    };
    msg.header.StdId = canVlvGeneralStdId;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendOpMode, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}


void canvlv_sendParamCrcRequest(uint16_t vcuNum){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_CFG_CRCPARAM_REQ	
    };
    msg.header.StdId = canVlvGeneralStdId;
		msg.dataStruct.code.um = vcuNum;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendParamCrcRequest, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}

void canvlv_sendCfgOn(uint16_t vcuNum){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_CFG_ON	
    };
    msg.header.StdId = canVlvGeneralStdId;
		msg.dataStruct.code.um = vcuNum;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendParamCrcRequest, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}

void canvlv_sendCfgAccept(void){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_CFG_ACCEPTPARAM	
    };
    msg.header.StdId = canVlvGeneralStdId;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendParamCrcRequest, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}




void canvlv_sendWriteParam(uint16_t index, uint32_t value){
    static item_t msg = {
        .header.IDE = CAN_ID_STD,
        .header.RTR = CAN_RTR_DATA,
        .header.DLC = CAN_STANDARD_DATA_LENGHT,
				.dataStruct.identifier.um = CANVLVMSG_CFG_WRITEPARAM	
    };
    msg.header.StdId = canVlvGeneralStdId;
		msg.dataStruct.code.um = index;
		msg.dataStruct.value.uw = value;
		int ret = sq_insert_tail((squeue_t*)&canVlvTx, &msg);
    #ifdef DEBUG_SWO
      if(ret < 0){
        TM_SWO_Printf("sq_insert_tail error in sendParamCrcRequest, ret = %d, size = %ui \n", ret, canVlvTx.size);
      }
   #endif
}


void TxVlvMailbox0CompleteCallback(CAN_HandleTypeDef *hcan){
    isCanVlvMailboxFree[0] = TRUE;
}
void TxVlvMailbox1CompleteCallback(CAN_HandleTypeDef *hcan){
    isCanVlvMailboxFree[1] = TRUE;
}
void TxVlvMailbox2CompleteCallback(CAN_HandleTypeDef *hcan){
    isCanVlvMailboxFree[2] = TRUE;
}

void RxVlvFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO0, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(canVlvRx.avail){
				sq_insert_tail((squeue_t*)&canVlvRx, &item);
		}
		return;
}

void RxVlvFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO1, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(canVlvRx.avail){
				sq_insert_tail((squeue_t*)&canVlvRx, &item);
		}
		return;
}


