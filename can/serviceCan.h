/**
 \file          serviceCan.h
 \author        Mikhail Kouniaev
 \date          March, 2024
 \brief         Библиотека с реализацией транспортного уровня OSI на CAN шине для 1 или 2 каналов CAN, обеспечивающего передачу сообщений между очередями Tx<->Rx и Rx<->Tx обменивающихся хостов 
 \note        	Для использования библиотеки в проекте должен содержаться файл конфигурирования serviceCan_config.h, определяющий:
 serviceCan_can1 - структура библиотеки HAL CAN_HandleTypeDef, соответсвующая используемому физическому приемо-передатчику, при использовании CAN1
 serviceCan_can2 - структура библиотеки HAL CAN_HandleTypeDef, соответсвующая используемому физическому приемо-передатчику, при использовании CAN2
 CAN_QUEUE_SIZE - длина очередей на прием и отправку для всех CAN каналов
 \note					Для использования библиотеки в проекте должен содержаться файл "defines.h", определяющий модификатор _extern

*/


#ifndef __SERVICECAN_H
#define __SERVICECAN_H

#include "squeue.h"
#include "defines.h"
#include "can.h"

#ifdef __cplusplus
 extern "C" {
#endif

#include "serviceCan_config.h"

#ifdef serviceCan_can1
	_extern squeue_t serviceCan_can1Tx;		/// < очередь на отправку
	_extern squeue_t serviceCan_can1Rx;		/// < очередь на прием
#endif


#ifdef serviceCan_can2
	_extern squeue_t serviceCan_can2Tx;		/// < очередь на отправку
	_extern squeue_t serviceCan_can2Rx;		/// < очередь на прием
#endif

#ifdef serviceCan_can1
	void serviceCan_can1_Init(void);
	void serviceCan_can1_Start(void);
	void serviceCan_can1_execTx(void);
#endif

#ifdef serviceCan_can2
	void serviceCan_can2_Init(void);
	void serviceCan_can2_Start(void);
	void serviceCan_can2_execTx(void);
#endif


#ifdef __cplusplus
}
#endif

#endif /* __SERVICECAN_H */
