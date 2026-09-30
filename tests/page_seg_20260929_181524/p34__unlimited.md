page_number [58, 48, 80, 60]16
header [649, 47, 948, 63]第1章 微弱信号检测与随机噪声
text [50, 80, 949, 143]例 1-2 随机相位正弦波  \( x(t)=A\sin(\omega_{0}t+\varphi) \) ， \( \varphi \)  在  \( 0\sim2\pi \)  之间均匀分布，幅度 A 为常数；随机幅度正弦波  \( y(t)=B\sin(\omega_{0}t) \) ，B 是与  \( \varphi \)  相互独立的随机量，B 的概率密度函数为
equation [369, 149, 946, 183]\[
p (B) = \frac {1}{\sqrt {2 \pi}} \exp [ - B ^ {2} / 2 ] \tag {1-33a}
\]
text [51, 190, 706, 209]试求 \(x(t)\) 和 \(y(t)\) 的统计特征量 \(\mu_x, \sigma_x^2, R_x(\tau), \mu_y, R_{xy}(\tau)\) 和 \(C_{xy}(\tau)\)。
text [97, 213, 329, 230]解：(1) \(x(t)\) 的均值 \(\mu_{x}\)
equation [213, 237, 792, 305]\[
\begin{array}{l} \mu_ {x} = E [ x (t) ] = \int x (t) p (x) \mathrm{d} x = \int_ {0} ^ {2 \pi} A \sin (\omega_ {0} t + \varphi) p (\varphi) \mathrm{d} \varphi \\ = \frac {A}{2 \pi} \int_ {0} ^ {2 \pi} \sin (\omega_ {0} t + \varphi) d \varphi = 0 \\ \end{array}
\]
text [98, 312, 284, 330](2) \(x(t)\) 的方差 \(\sigma_x^2\)
equation [286, 336, 714, 429]\[
\begin{array}{l} \sigma_ {x} ^ {2} = E [ x (t) - \mu_ {x} ] ^ {2} = E [ A ^ {2} \sin^ {2} (\omega_ {0} t + \varphi) ] \\ = \frac {A ^ {2}}{2} E [ 1 - \cos (2 \omega_ {0} t + 2 \varphi) ] \\ = \frac {A ^ {2}}{2} - \frac {A ^ {2}}{2} \frac {1}{2 \pi} \int_ {0} ^ {2 \pi} \cos (2 \omega_ {0} t + 2 \varphi) d \varphi = \frac {A ^ {2}}{2} \\ \end{array}
\]
text [98, 436, 391, 453](3) \(x(t)\) 的自相关函数 \(R_{x}(\tau)\)
equation [223, 459, 780, 598]\[
\begin{array}{l} R _ {x} (\tau) = E [ x (t) x (t - \tau) ] \\ = E \left[ A \sin \left(\omega_ {0} t + \varphi\right) A \sin \left(\omega_ {0} (t - \tau) + \varphi\right) \right] \\ = A ^ {2} E \left[ \sin \left(\omega_ {0} t + \varphi\right) \sin \left(\omega_ {0} (t - \tau) + \varphi\right) \right] \\ = \frac {A ^ {2}}{2} E [ \cos (\omega_ {0} \tau) - \cos (\omega_ {0} (2 t - \tau) + 2 \varphi) ] \\ = \frac {A ^ {2}}{2} \cos (\omega_ {0} \tau) - \frac {A ^ {2}}{2} \frac {1}{2 \pi} \int_ {0} ^ {2 \pi} \cos (\omega_ {0} (2 t - \tau) + 2 \varphi) d \varphi \\ \end{array}
\]
text [52, 604, 436, 621]上式右边的第二项积分结果为零,所以
equation [393, 628, 607, 656]\[
R _ {x} (\tau) = \frac {A ^ {2}}{2} \cos (\omega_ {0} \tau)
\]
text [50, 659, 948, 703]这也就证明了自相关函数的特点(4): 对于正弦信号, 不管其初相位如何, 其自相关函数总是以余弦函数的形式出现。
text [97, 709, 334, 727](4) \(y(t)\) 的均值 \(\mu_{y}\)
text [94, 732, 934, 750]对比式(1-12)与式(1-33a)可知， \( y(t) \) 的幅值B是高斯分布，其均值为零，方差为1，得
equation [214, 752, 789, 772]\[
\mu_ {y} = E [ y (t) ] = E [ B \cos (\omega_ {0} t) ] = E [ B ] E [ \cos (\omega_ {0} t) ] = 0
\]
text [96, 776, 557, 794]这也就证明了自相关函数的特点(4): 对于正弦信号, 不管其初相位如何, 其自相关函数总
text [51, 797, 320, 814]是以余弦函数的形式出现。
text [97, 710, 284, 728](4) \(y(t)\) 的均值 \(\mu_{y}\)
text [94, 732, 934, 750]对比式(1-12)与式(1-33a)可知， \( y(t) \) 的幅值B是高斯分布，其均值为零，方差为1，得
equation [212, 754, 789, 773]\[
\mu_ {y} = E [ y (t) ] = E [ B \cos (\omega_ {0} t) ] = E [ B ] E [ \cos (\omega_ {0} t) ] = 0
\]
text [96, 777, 560, 795](5) 互相关函数  \( R_{xy}(\tau) \)  和互协方差函数  \( C_{xy}(\tau) \)
text [96, 800, 418, 817]因为 \(B\) 和 \(\varphi\) 相互独立，所以可得
equation [259, 822, 741, 909]\[
\begin{array}{l} R _ {x y} (\tau) = E [ x (t - \tau) y (t) ] \\ = E \left[ A \sin \left(\omega_ {0} (t - \tau) + \varphi\right) B \sin \left(\omega_ {0} t\right) \right] \\ = E \left[ A \sin \left(\omega_ {0} (t - \tau) + \varphi\right) E \left[ B \sin \left(\omega_ {0} t\right) \right] \right. \\ = \mu_ {x} \mu_ {y} = 0 \\ \end{array}
\]
equation [260, 914, 541, 932]\[
C _ {x y} (\tau) = R _ {x y} (\tau) - \mu_ {x} \mu_ {y} = 0
\]