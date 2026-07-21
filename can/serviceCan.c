#include "serviceCan.h"

#ifdef serviceCan_can1
	volatile item_t can1_TxA[CAN_QUEUE_SIZE];
	volatile item_t can1_RxA[CAN_QUEUE_SIZE];
	volatile flag_t can1_isMailboxFree[5];

	void can1_TxMailbox0CompleteCallback(CAN_HandleTypeDef *hcan);
	void can1_TxMailbox1CompleteCallback(CAN_HandleTypeDef *hcan);
	void can1_TxMailbox2CompleteCallback(CAN_HandleTypeDef *hcan);
	void can1_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan);
	void can1_RxFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan);
#endif

#ifdef serviceCan_can2
	volatile item_t can2_TxA[CAN_QUEUE_SIZE];
	volatile item_t can2_RxA[CAN_QUEUE_SIZE];
	volatile flag_t can2_isMailboxFree[5];

	void can2_TxMailbox0CompleteCallback(CAN_HandleTypeDef *hcan);
	void can2_TxMailbox1CompleteCallback(CAN_HandleTypeDef *hcan);
	void can2_TxMailbox2CompleteCallback(CAN_HandleTypeDef *hcan);
	void can2_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan);
	void can2_RxFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan);
#endif


void initRxTxSqueue(squeue_t *rx, squeue_t *tx){					/// TODO: реализовать инициализацию в squeue.c
	
  tx->data_size = CAN_QUEUE_SIZE;
  tx->avail = CAN_QUEUE_SIZE;
  tx->size = 0;
  tx->head = 0;
  tx->tail = 0;
  tx->isTailUnlocked = true;
  tx->isHeadUnlocked = true;

  rx->data_size = CAN_QUEUE_SIZE;
  rx->avail = CAN_QUEUE_SIZE;
  rx->size = 0;
  rx->head = 0;
  rx->tail = 0;
  rx->isTailUnlocked = true;
  rx->isHeadUnlocked = true;
}


/**
	* @brief Функция настройки прерываний CAN интерфейса
	* @Warning Примечание: ф-ции инициализации HAL в явном виде не настраивают источники прерываний
  * @retval None
  */
void setCanIrqParams(CAN_HandleTypeDef *can){       // прерывание при ...  
    can->Instance->IER |= CAN_IER_TMEIE;   // освобождении исх. почт. ящика
    can->Instance->IER |= CAN_IER_FMPIE0;  // получение пакета в FIFO0
    can->Instance->IER &= ~CAN_IER_FFIE0;  // заполнении FIFO0 
    can->Instance->IER |= CAN_IER_FOVIE0;  // переполнении FIFO0 
    can->Instance->IER |= CAN_IER_FMPIE1;  // получение пакета в FIFO1
    can->Instance->IER &= ~CAN_IER_FFIE1;  // заполнении FIFO1 
    can->Instance->IER |= CAN_IER_FOVIE1;  // переполнении FIFO1
    can->Instance->IER &= ~CAN_IER_EWGIE;  // дост-и пред-го (>= 96) ур-ня оши-к
    can->Instance->IER |= CAN_IER_EPVIE;   // дост-и пассивного ур-ня ошибок
    can->Instance->IER |= CAN_IER_BOFIE;   // переходе в режим bus-off
    can->Instance->IER &= ~CAN_IER_LECIE;  // возникновении ошибки приёма-передачи
    can->Instance->IER &= ~CAN_IER_ERRIE;  // возникновении ошибки
    can->Instance->IER &= ~CAN_IER_WKUIE;  // выходе из спящего режима
    can->Instance->IER &= ~CAN_IER_SLKIE;  // переходе в спящий режим
}

#ifdef serviceCan_can1
void serviceCan_can1_Init(void){
	#ifdef DEBUG_SWO
			TM_SWO_Printf("\n CAN1 init begin \n");
	#endif
	serviceCan_can1Tx.data = can1_TxA;
  serviceCan_can1Rx.data = can1_RxA;
	initRxTxSqueue(&serviceCan_can1Rx, &serviceCan_can1Tx);

	can1_isMailboxFree[1] = true;
	can1_isMailboxFree[2] = true;
	can1_isMailboxFree[4] = true;	
	setCanIrqParams(&serviceCan_can1);

	// Регистрация callback-ов
	// Важно: регистрация происходит в STM32CubeMX Project Manager > Advanced Settings > Register Callback 
	HAL_CAN_RegisterCallback(&serviceCan_can1, HAL_CAN_RX_FIFO0_MSG_PENDING_CB_ID, can1_RxFifo0MsgPendingCallback);
	HAL_CAN_RegisterCallback(&serviceCan_can1, HAL_CAN_RX_FIFO1_MSG_PENDING_CB_ID, can1_RxFifo1MsgPendingCallback);   
	HAL_CAN_RegisterCallback(&serviceCan_can1, HAL_CAN_TX_MAILBOX0_COMPLETE_CB_ID, can1_TxMailbox0CompleteCallback);
	HAL_CAN_RegisterCallback(&serviceCan_can1, HAL_CAN_TX_MAILBOX1_COMPLETE_CB_ID, can1_TxMailbox1CompleteCallback);
	HAL_CAN_RegisterCallback(&serviceCan_can1, HAL_CAN_TX_MAILBOX2_COMPLETE_CB_ID, can1_TxMailbox2CompleteCallback);

//	setNewApiCanBusFilters();
}
#endif


#ifdef serviceCan_can2
void serviceCan_can2_Init(void){
	#ifdef DEBUG_SWO
			TM_SWO_Printf("\n CAN1 init begin \n");
	#endif
	serviceCan_can2Tx.data = can2_TxA;
  serviceCan_can2Rx.data = can2_RxA;
	initRxTxSqueue(&serviceCan_can2Rx, &serviceCan_can2Tx);

	can2_isMailboxFree[1] = true;
	can2_isMailboxFree[2] = true;
	can2_isMailboxFree[4] = true;	
	setCanIrqParams(&serviceCan_can2);

	// Регистрация callback-ов
	// Важно: регистрация происходит в STM32CubeMX Project Manager > Advanced Settings > Register Callback 
	HAL_CAN_RegisterCallback(&serviceCan_can2, HAL_CAN_RX_FIFO0_MSG_PENDING_CB_ID, can2_RxFifo0MsgPendingCallback);
	HAL_CAN_RegisterCallback(&serviceCan_can2, HAL_CAN_RX_FIFO1_MSG_PENDING_CB_ID, can2_RxFifo1MsgPendingCallback);   
	HAL_CAN_RegisterCallback(&serviceCan_can2, HAL_CAN_TX_MAILBOX0_COMPLETE_CB_ID, can2_TxMailbox0CompleteCallback);
	HAL_CAN_RegisterCallback(&serviceCan_can2, HAL_CAN_TX_MAILBOX1_COMPLETE_CB_ID, can2_TxMailbox1CompleteCallback);
	HAL_CAN_RegisterCallback(&serviceCan_can2, HAL_CAN_TX_MAILBOX2_COMPLETE_CB_ID, can2_TxMailbox2CompleteCallback);

//	setNewApiCanBusFilters();
}
#endif


#ifdef serviceCan_can1
void serviceCan_can1_Start(void){
	if(HAL_OK != HAL_CAN_Start(&serviceCan_can1)){
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN1 not started\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN1 has been started\n");
			#endif
	}
	if(HAL_OK != HAL_CAN_ActivateNotification(&serviceCan_can1,
																						CAN_IT_RX_FIFO0_MSG_PENDING | 
																						CAN_IT_TX_MAILBOX_EMPTY))
	{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN1 not activated\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN1 has been activated\n");
			#endif
	}
}
#endif


#ifdef serviceCan_can2
void serviceCan_can2_Start(void){
	if(HAL_OK != HAL_CAN_Start(&serviceCan_can2)){
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN2 not started\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN2 has been started\n");
			#endif
	}
	if(HAL_OK != HAL_CAN_ActivateNotification(&serviceCan_can2,
																						CAN_IT_RX_FIFO0_MSG_PENDING | 
																						CAN_IT_TX_MAILBOX_EMPTY))
	{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN2 not activated\n");
			#endif
			Error_Handler();
	}else{
			#ifdef DEBUG_SWO
					TM_SWO_Printf("CAN2 has been activated\n");
			#endif
	}
}
#endif


#ifdef serviceCan_can1
void serviceCan_can1_execTx(void){			///> обработка очереди на отправку в CAN
		HAL_StatusTypeDef ret;
		if(serviceCan_can1Tx.size && (can1_isMailboxFree[1] | 
																	can1_isMailboxFree[2] |
																	can1_isMailboxFree[4])){
				new_api_canmsg_t *pMsg = sq_head((squeue_t*)&serviceCan_can1Tx);
				uint32_t mailbox;
				if(NULL != pMsg)				{
						ret = HAL_CAN_AddTxMessage(&serviceCan_can1, (CAN_TxHeaderTypeDef*)&pMsg->header, pMsg->data, &mailbox);
						if(HAL_OK == ret){
								can1_isMailboxFree[mailbox] = false;
								sq_remove_head((squeue_t*)&serviceCan_can1Tx);
						}else{}                
//								TM_SWO_Printf("Can message send error, ret = %u \n", ret);
				}
		#ifdef DEBUG_SWO
				else{
						TM_SWO_Printf("Can 1 tx message error. Msg is null!");
				}
		#endif
		}
}
#endif


#ifdef serviceCan_can2
void serviceCan_can2_execTx(void){			///> обработка очереди на отправку в CAN
		HAL_StatusTypeDef ret;
		if(serviceCan_can2Tx.size && (can2_isMailboxFree[1] | 
																	can2_isMailboxFree[2] |
																	can2_isMailboxFree[4])){
				new_api_canmsg_t *pMsg = sq_head((squeue_t*)&serviceCan_can2Tx);
				uint32_t mailbox;
				if(NULL != pMsg)				{
						ret = HAL_CAN_AddTxMessage(&serviceCan_can2, (CAN_TxHeaderTypeDef*)&pMsg->header, pMsg->data, &mailbox);
						if(HAL_OK == ret){
								can2_isMailboxFree[mailbox] = false;
								sq_remove_head((squeue_t*)&serviceCan_can2Tx);
						}else{}                
//								TM_SWO_Printf("Can message send error, ret = %u \n", ret);
				}
		#ifdef DEBUG_SWO
				else{
						TM_SWO_Printf("Can 2 tx message error. Msg is null!");
				}
		#endif
		}
}
#endif

	
#ifdef serviceCan_can1
void can1_TxMailbox0CompleteCallback(CAN_HandleTypeDef *hcan){
    can1_isMailboxFree[1] = true;
}
void can1_TxMailbox1CompleteCallback(CAN_HandleTypeDef *hcan){
    can1_isMailboxFree[2] = true;
}
void can1_TxMailbox2CompleteCallback(CAN_HandleTypeDef *hcan){
    can1_isMailboxFree[4] = true;
}
void can1_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO0, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(serviceCan_can1Rx.avail){
				sq_insert_tail((squeue_t*)&serviceCan_can1Rx, &item);
		}
		return;
}
void can1_RxFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO1, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(serviceCan_can1Rx.avail){
				sq_insert_tail((squeue_t*)&serviceCan_can1Rx, &item);
		}
		return;
}
#endif


#ifdef serviceCan_can2
void can2_TxMailbox0CompleteCallback(CAN_HandleTypeDef *hcan){
    can2_isMailboxFree[1] = true;
}
void can2_TxMailbox1CompleteCallback(CAN_HandleTypeDef *hcan){
    can2_isMailboxFree[3] = true;
}
void can2_TxMailbox2CompleteCallback(CAN_HandleTypeDef *hcan){
    can2_isMailboxFree[4] = true;
}
void can2_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO0, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(serviceCan_can2Rx.avail){
				sq_insert_tail((squeue_t*)&serviceCan_can2Rx, &item);
		}
		return;
}
void can2_RxFifo1MsgPendingCallback(CAN_HandleTypeDef *hcan){
		item_t item;
		HAL_CAN_GetRxMessage(   hcan, 
														CAN_RX_FIFO1, 
														(CAN_RxHeaderTypeDef*)&item.header, 
														item.data);
		if(serviceCan_can2Rx.avail){
				sq_insert_tail((squeue_t*)&serviceCan_can2Rx, &item);
		}
		return;
}
#endif
