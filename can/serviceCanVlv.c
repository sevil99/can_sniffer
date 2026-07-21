#include "serviceCanVlv.h"
#include "serviceCanMain.h"
#include "serviceMd.h"
#include "squeue.h"
#include "defines.h"
#include "global.h"
#include "ModbusRTU.h"
#include "string.h"
//#include "serviceParam.h"

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
	
	canVlvGeneralStdId 	= KSIVLV_KSIA1_GENERAL;
	canVlvNoticeStdId 	= KSIVLV_KSIA1_NOTICE;
	canVlvServiceStdId 	= KSIVLV_KSIA1_SERVICE; 

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
    CAN_FilterTypeDef can2Filter = {
//        .FilterIdHigh						=	CIDVLV_VCU1_NOTICE|CIDVLV_VCU1_GENERAL|CIDVLV_VCU1_SERVICE<<5, // 0x0000,		  								//CID_ICM_GENERAL		<< 5
//        .FilterIdLow						=	0xFFF0<<5, //0x0000,											//CID_CFG1_GENERAL	<< 5
//        .FilterMaskIdHigh				=	0x0000<<5, //0x0000,											//CID_ICM_NOTICE		<< 5 
//        .FilterMaskIdLow				=	0x0000<<5,	//0x0000,											//CID_CFG1_NOTICE		<< 5
//        .FilterIdHigh						=	0x0000, 
        .FilterIdHigh						=	0x0000,  
        .FilterIdLow						=	0x0000, 
        .FilterMaskIdHigh				=	0xFFE0, 
        .FilterMaskIdLow				=	0x0000,
        .FilterFIFOAssignment		=	CAN_RX_FIFO0,								//
        .FilterBank							=	0,
        .FilterMode							=	CAN_FILTERMODE_IDMASK, //CAN_FILTERMODE_IDLIST,			//CAN_FILTERMODE_IDMASK 
        .FilterScale						=	CAN_FILTERSCALE_16BIT,			//CAN_FILTERSCALE_16BIT
        .FilterActivation				=	ENABLE,
//        .SlaveStartFilterBank		=	4 
		};
    if(HAL_OK != HAL_CAN_ConfigFilter(&hcan2, &can2Filter)){
        #ifdef DEBUG_SWO
             TM_SWO_Printf("CAN filter config error");
        #endif
        Error_Handler();
    }
}





void canVlv_proceedRxMsg(void){   ///> обработка входящих сообщений в CAN
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



uint8_t canBufferIndex = 0;  // Индекс для записи в буфер

uint8_t modbusBufferIndex = 0;  // Индекс для записи в буфер
_extern volatile CanToModbusMsg_t CanToModbusMsgBuffer[CAN_TO_MODBUS_BUFFER_SIZE]; 


void addToCanBuffer(uint32_t id, DataType type, 
	float Offset, bool RewriteOffset,
		float Knock, bool RewriteKnock, 
			uint32_t SyncErr, bool RewriteSyncErr,
				uint8_t byteVal, uint8_t CanIndex) {
    if (canBufferIndex < CAN_TO_MODBUS_BUFFER_SIZE) {
        CanToModbusMsgBuffer[CanIndex].id = id;
        CanToModbusMsgBuffer[CanIndex].type = type;
        
       
					if(RewriteKnock){ CanToModbusMsgBuffer[CanIndex].data.Knock = Knock;}
          if(RewriteOffset){  CanToModbusMsgBuffer[CanIndex].data.Offset = Offset;}
					 
       
					if(RewriteSyncErr){  CanToModbusMsgBuffer[CanIndex].data.ping = SyncErr;}
            
        
      //  canBufferIndex++;
    } else {
			// Логика для переполнения буфера (например, перезапись старых данных) тут дублироание логики
        canBufferIndex = 0;  // Перезапись старых данных
        CanToModbusMsgBuffer[CanIndex].id = id;
        CanToModbusMsgBuffer[CanIndex].type = type;
        
        if (type == DATA_TYPE_FLOAT) {
					if(RewriteKnock){ CanToModbusMsgBuffer[CanIndex].data.Knock = Knock;}
          if(RewriteOffset){  CanToModbusMsgBuffer[CanIndex].data.Offset = Offset;}
					 
        } else if (type == DATA_TYPE_BYTE) {
					if(RewriteSyncErr){  CanToModbusMsgBuffer[CanIndex].data.ping = SyncErr;}
            
        }
    }
}


static void writeFloatToInputRegistersCdab(uint16_t regIndex, float value) {
    uint8_t data[sizeof(value)];
    memcpy(data, &value, sizeof(value));

    // STM32 stores DCBA; Modbus serializes these registers as CDAB.
    mdbs_InputRegisters[regIndex].us[1] = data[1];
    mdbs_InputRegisters[regIndex].us[0] = data[0];
    mdbs_InputRegisters[regIndex + 1].us[1] = data[3];
    mdbs_InputRegisters[regIndex + 1].us[0] = data[2];
}


void writeCanDataToInputRegisters(uint8_t CanIndex, uint8_t ModbusIndex) {
    uint16_t regIndex = ModbusIndex; // Начинаем с регистра, определенного в canBufferIndex

    // Записываем SyncErr
    if (CanToModbusMsgBuffer[CanIndex].type == DATA_TYPE_UINT32) {
			  // SyncErr
        uint32_t syncErr = CanToModbusMsgBuffer[CanIndex].data.SyncErr;
        uint8_t* bytePointer = (uint8_t*)&syncErr;
        mdbs_InputRegisters[regIndex].us[1] = bytePointer[0];
        mdbs_InputRegisters[regIndex].us[0] = bytePointer[1];
        regIndex++;
        mdbs_InputRegisters[regIndex].us[1] = bytePointer[2];
        mdbs_InputRegisters[regIndex].us[0] = bytePointer[3];
        regIndex++;
    }

    // Записываем Knock и Offset, если тип данных является float
    if (CanToModbusMsgBuffer[CanIndex].type == DATA_TYPE_FLOAT) {
        // Knock
			  regIndex = ModbusIndex+2;
        float floatData = CanToModbusMsgBuffer[CanIndex].data.Knock;
        writeFloatToInputRegistersCdab(regIndex, floatData);
        regIndex += 2;

        // Offset
        floatData = CanToModbusMsgBuffer[CanIndex].data.Offset;
        writeFloatToInputRegistersCdab(regIndex, floatData);
        regIndex += 2;
    }
}


		
void writePingDataToInputRegisters() {
    uint16_t regIndex = 0; // Один индекс для обоих состояний

    // Запись StateA
    uint8_t StateDataA = StateCylA.value;
    mdbs_InputRegisters[regIndex].us[1] = 0;  // старший байт
    mdbs_InputRegisters[regIndex].us[0] = StateDataA;  // младший байт
    regIndex++;

    // Запись StateB
    uint8_t StateDataB = StateCylB.value;
    mdbs_InputRegisters[regIndex].us[1] = 0;  // старший байт
    mdbs_InputRegisters[regIndex].us[0] = StateDataB;  // младший байт
    regIndex++;
}


/*
В буффер\регистры Modbus складываются подряд данные размером 32 бита (4 байта) [SyncErr]  и два значения типа float (4 байта+4 байта) [Knock] [Offset].
Размера данных в регистрах Modbus, имеет длину 16 бит (2 байта).

32-битные данные (4 байта) занимают два 16-битных регистра.
Каждый float (также 4 байта) тоже занимает два 16-битных регистра.
Расчет смещения:
Для 32-битных данных (4 байта) ты используешь 2 регистра.
Для одного float (4 байта) — 2 регистра.
Для второго float (4 байта) — еще 2 регистра.
Таким образом, итоговое смещение будет:

32-битные данные → 2 регистра (4 байта).
Первый float → 2 регистра (4 байта).
Второй float → 2 регистра (4 байта).
Итого: 6 регистров или 12 байт.

Пример записи:
Предположим, ты начинаешь запись с регистра 0:

Регистр i+0 и i+1 — для 32-битного значения.
Регистр i+2 и i+3 — для первого float.
Регистр i+4 и i+5 — для второго float.

Modbus сообщение для цилиндра A1 i=0:
02 04 00 00 00 06

Modbus сообщение для цилиндра A2 i =1:
02 04 00 06 00 06

*/

#define KSI_COMMUNICATION_TIMEOUT_MS       10000U
#define KSI_COMM_STATE_UPDATE_PERIOD_MS      100U


void canVlv_updateCommunicationState(void)
{
    uint32_t currentTime = HAL_GetTick();

    for (uint32_t ksiNum = 0U; ksiNum < KSI_CAN_DATA_COUNT; ksiNum++) {
        if ((uint32_t)(currentTime - lastMessageTime[ksiNum]) >= KSI_COMMUNICATION_TIMEOUT_MS) {
            if (ksiNum < 10U) {
                StateCylA.value &= (uint16_t)~(1U << ksiNum);
            } else {
                StateCylB.value &= (uint16_t)~(1U << (ksiNum - 10U));
            }
        }
    }
}

int32_t parseCanVlvMsg(item_t *item)	{
	static int32_t ksi_num = -1;
	if(NULL == item)
		return -1;
  switch(item->header.StdId){
				case KSIVLV_KSIA1_NOTICE:
				case KSIVLV_KSIA1_GENERAL:
				case KSIVLV_KSIA1_SERVICE:		{StateCylA.field0 = 1;  ksi_num = 0;} 	break; 
				case KSIVLV_KSIA2_NOTICE:
				case KSIVLV_KSIA2_GENERAL:
				case KSIVLV_KSIA2_SERVICE:		{StateCylA.field1 = 1;  ksi_num = 1;} 	break; 
				case KSIVLV_KSIA3_NOTICE:
				case KSIVLV_KSIA3_GENERAL:
				case KSIVLV_KSIA3_SERVICE:		{StateCylA.field2 = 1;  ksi_num = 2;} 	break; 
				case KSIVLV_KSIA4_NOTICE:
				case KSIVLV_KSIA4_GENERAL:
				case KSIVLV_KSIA4_SERVICE:		{StateCylA.field3 = 1;  ksi_num = 3;} 	break; 
				case KSIVLV_KSIA5_NOTICE:
				case KSIVLV_KSIA5_GENERAL:
				case KSIVLV_KSIA5_SERVICE:		{StateCylA.field4 = 1;  ksi_num = 4;} 	break; 
				case KSIVLV_KSIA6_NOTICE:
				case KSIVLV_KSIA6_GENERAL:
				case KSIVLV_KSIA6_SERVICE:		{StateCylA.field5 = 1;  ksi_num = 5;} 	break; 
				case KSIVLV_KSIA7_NOTICE:
				case KSIVLV_KSIA7_GENERAL:
				case KSIVLV_KSIA7_SERVICE:		{StateCylA.field6 = 1;  ksi_num = 6;} 	break; 
				case KSIVLV_KSIA8_NOTICE:
				case KSIVLV_KSIA8_GENERAL:
				case KSIVLV_KSIA8_SERVICE:		{StateCylA.field7 = 1;  ksi_num = 7;} 	break; 
				case KSIVLV_KSIA9_NOTICE:
				case KSIVLV_KSIA9_GENERAL:
				case KSIVLV_KSIA9_SERVICE:		{StateCylA.field8 = 1;  ksi_num = 8;} 	break; 
				case KSIVLV_KSIA10_NOTICE:
				case KSIVLV_KSIA10_GENERAL:
				case KSIVLV_KSIA10_SERVICE:		{StateCylA.field9 = 1;  ksi_num = 9;} 	break; 
				case KSIVLV_KSIB1_NOTICE:
				case KSIVLV_KSIB1_GENERAL:
				case KSIVLV_KSIB1_SERVICE:		{StateCylB.field0 = 1;  ksi_num = 10;} 	break; 
				case KSIVLV_KSIB2_NOTICE:
				case KSIVLV_KSIB2_GENERAL:
				case KSIVLV_KSIB2_SERVICE:		{StateCylB.field1 = 1;  ksi_num = 11;} 	break;
				case KSIVLV_KSIB3_NOTICE:
				case KSIVLV_KSIB3_GENERAL:
				case KSIVLV_KSIB3_SERVICE:		{StateCylB.field2 = 1;  ksi_num = 12;} 	break;
				case KSIVLV_KSIB4_NOTICE:
				case KSIVLV_KSIB4_GENERAL:
				case KSIVLV_KSIB4_SERVICE:		{StateCylB.field3 = 1;  ksi_num = 13;} 	break;
				case KSIVLV_KSIB5_NOTICE:
				case KSIVLV_KSIB5_GENERAL:
				case KSIVLV_KSIB5_SERVICE:		{StateCylB.field4 = 1;  ksi_num = 14;} 	break;
				case KSIVLV_KSIB6_NOTICE:
				case KSIVLV_KSIB6_GENERAL:
				case KSIVLV_KSIB6_SERVICE:		{StateCylB.field5 = 1;  ksi_num = 15;}	break;
				case KSIVLV_KSIB7_NOTICE:
				case KSIVLV_KSIB7_GENERAL:
				case KSIVLV_KSIB7_SERVICE:		{StateCylB.field6 = 1;  ksi_num = 16;} 	break;
				case KSIVLV_KSIB8_NOTICE:
				case KSIVLV_KSIB8_GENERAL:
				case KSIVLV_KSIB8_SERVICE:		{StateCylB.field7 = 1;  ksi_num = 17;} 	break;
				case KSIVLV_KSIB9_NOTICE:
				case KSIVLV_KSIB9_GENERAL:
				case KSIVLV_KSIB9_SERVICE:		{StateCylB.field8 = 1;  ksi_num = 18;} 	break;
				case KSIVLV_KSIB10_NOTICE:
				case KSIVLV_KSIB10_GENERAL:
				case KSIVLV_KSIB10_SERVICE:		{StateCylB.field9 = 1;  ksi_num = 19;} 	break;
	default: 		ksi_num =  -1;
}
	
 uint32_t KSIVLV_BASES[] = {KSIVLV_KSIA1_BASE, KSIVLV_KSIA2_BASE, KSIVLV_KSIA3_BASE, 
                               KSIVLV_KSIA4_BASE, KSIVLV_KSIA5_BASE, KSIVLV_KSIA6_BASE, 
                               KSIVLV_KSIA7_BASE, KSIVLV_KSIA8_BASE, KSIVLV_KSIA9_BASE, KSIVLV_KSIA10_BASE,
															 KSIVLV_KSIB1_BASE, KSIVLV_KSIB2_BASE, KSIVLV_KSIB3_BASE, 
                               KSIVLV_KSIB4_BASE, KSIVLV_KSIB5_BASE, KSIVLV_KSIB6_BASE, 
                               KSIVLV_KSIB7_BASE, KSIVLV_KSIB8_BASE, KSIVLV_KSIB9_BASE, KSIVLV_KSIB10_BASE,
		};

    // Проверка допустимого значения ksi_num
    if (ksi_num < 0 || (uint32_t)ksi_num >= KSI_CAN_DATA_COUNT) return -1;

    lastMessageTime[ksi_num] =  HAL_GetTick();

		
    switch (item->dataStruct.code.um) {
    case CANVLVMSG_KSI_SYNC: {
        uint32_t value = item->dataStruct.value.uw;
        if (value != 0) {  // Защита от нуля
            KsiCanData[ksi_num].Sync = value;
        }
        break;
    }
    case CANVLVMSG_KSI_KNOCK: {
        float value = item->dataStruct.value.f;
        if (value != 0.0f) {  // Защита от нуля
            KsiCanData[ksi_num].Knock = value;
        }
        break;
    }
    case CANVLVMSG_KSI_OFFSET: {
        float value = item->dataStruct.value.f;
//        if (value != 0.0f) {  // Защита от нуля
            KsiCanData[ksi_num].Offset = value;
//       }
        break;
    }
    default:
            return -1;
    }
		



		return 0;
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
//				sq_insert_tail((squeue_t*)&canTx, &item);
		
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
//				sq_insert_tail((squeue_t*)&canTx, &item);
		}
		return;
}


